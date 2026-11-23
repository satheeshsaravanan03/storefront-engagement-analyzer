"""Tests for adjusting the marks of a finished mall places job: POST /api/jobs/{id}/recompute (no detection model)."""

import json
import os
import tempfile
from pathlib import Path

os.environ["OUTPUT_DIR"] = tempfile.mkdtemp()   # before main is imported: jobs are kept here, not in the real folder

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import main
import processor

W, H, FPS = 320, 240, 24.0


def shop(**over):
    """A shop whose door is the vertical line x = 160 and whose pin is 112 px to the right of it."""
    p = {"name": "Shop A", "door": [[0.5, 0.3], [0.5, 0.7]], "inside": [0.85, 0.5]}
    p.update(over)
    return p


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def job(tmp_path):
    """A finished mall places job: a short blank video, and one person who walks through the door and is lost."""
    job_id = "recomp01"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    video = job_dir / "input.mp4"
    out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(90):
        out.write(np.full((H, W, 3), 120, np.uint8))
    out.release()

    walk = [(2 * i, 100 + 6 * i - 12, 60.0, 100 + 6 * i + 12, 120.0) for i in range(26)]   # crosses x = 160, ends at x = 250
    processor.save_tracks(str(job_dir), {"width": W, "height": H, "fps": FPS, "stride": 2, "last_fid": 89,
                                         "tracks": {1: walk}, "person_of": {1: 1}})
    (job_dir / "place_metrics.json").write_text(json.dumps({"settings": {"model": "yolov8m.pt"}}), encoding="utf-8")
    main.jobs.create(job_id, {
        "status": "done", "mode": "places", "video_path": str(video), "job_dir": str(job_dir),
        "config": {"mode": "places"}, "filename": "x.mp4", "created_at": 0,
        "stats": {"duration_sec": 3.8, "resolution": f"{W}x{H}", "source_fps": FPS, "total_frames": 90,
                  "tracks": 1, "people": 1, "stay_sec": 2.5, "stop_sec": 3.0},
    })
    yield job_id, job_dir
    main.jobs.delete(job_id)


def post(client, job_id, places, **extra):
    return client.post(f"/api/jobs/{job_id}/recompute", json={"places": places, **extra})


def test_new_marks_change_the_result_and_rewrite_the_files(client, job):
    job_id, job_dir = job

    r = post(client, job_id, [shop()])

    assert r.status_code == 200
    body = r.json()
    assert [e["event"] for e in body["places_result"]["events"]] == ["enter"]
    assert body["stats"]["entered"] == 1
    assert "enter" in (job_dir / "place_events.csv").read_text(encoding="utf-8-sig")
    video = cv2.VideoCapture(str(job_dir / "annotated.mp4"))
    assert video.isOpened() and video.grab()                      # the annotated video was written again
    video.release()
    assert main.jobs.get(job_id)["config"]["places"][0]["name"] == "Shop A"     # the marks used are the marks kept


def test_marks_somewhere_else_give_a_different_answer(client, job):
    job_id, _ = job
    post(client, job_id, [shop()])

    r = post(client, job_id, [shop(door=[[0.1, 0.3], [0.1, 0.7]], inside=[0.3, 0.5])])    # the walker never crosses this line

    assert r.status_code == 200
    assert r.json()["places_result"]["events"] == []
    assert r.json()["stats"]["entered"] == 0


def test_the_settings_can_change_with_the_marks(client, job):
    job_id, _ = job
    r = post(client, job_id, [shop()], stay_sec=1.0, stop_sec=5.0)
    assert r.status_code == 200
    assert (r.json()["stats"]["stay_sec"], r.json()["stats"]["stop_sec"]) == (1.0, 5.0)


@pytest.mark.parametrize("places", [[], [shop(door=[[0.5, 0.3], [0.5, 0.31]])], [shop(front=5)], "x"])
def test_bad_marks_are_refused_and_nothing_is_changed(client, job, places):
    job_id, _ = job
    before = main.jobs.get(job_id)["stats"]
    r = post(client, job_id, places)
    assert r.status_code in (400, 422)
    assert main.jobs.get(job_id)["stats"] == before


def test_a_stay_time_that_is_not_a_number_is_refused(client, job):
    job_id, _ = job
    body = '{"places": ' + json.dumps([shop()]) + ', "stay_sec": NaN}'          # a client can send this text; Python's parser takes it
    r = client.post(f"/api/jobs/{job_id}/recompute", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_an_unknown_job_is_not_found(client):
    assert post(client, "nope", [shop()]).status_code == 404


def test_a_stand_attention_job_has_no_shops_to_adjust(client, job):
    job_id, _ = job
    main.jobs.update(job_id, {"mode": "stand"})
    assert post(client, job_id, [shop()]).status_code == 400


def test_a_job_from_before_tracks_were_saved_cannot_be_adjusted(client, job):
    job_id, job_dir = job
    (job_dir / "tracks.json").unlink()
    r = post(client, job_id, [shop()])
    assert r.status_code == 409 and "Upload the video again" in r.json()["detail"]
    assert main.jobs.get(job_id) is not None and "can_adjust" not in main._build_response(job_id, main.jobs.get(job_id)) or \
        main._build_response(job_id, main.jobs.get(job_id))["can_adjust"] is False


def test_a_job_that_is_busy_is_refused(client, job):
    job_id, _ = job
    main.jobs.update(job_id, {"recomputing": True})
    assert post(client, job_id, [shop()]).status_code == 409


def test_the_response_says_whether_the_marks_can_be_adjusted(job):
    job_id, job_dir = job
    assert main._build_response(job_id, main.jobs.get(job_id))["can_adjust"] is True


def test_the_video_link_changes_when_the_video_is_written_again(client, job):
    job_id, job_dir = job
    post(client, job_id, [shop()])                                  # writes annotated.mp4
    first =main._build_response(job_id, main.jobs.get(job_id))["annotated_video_url"]
    assert "/api/download/" in first and "?v=" in first
    video = job_dir / "annotated.mp4"
    stat = video.stat()
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert main._build_response(job_id, main.jobs.get(job_id))["annotated_video_url"] != first


def test_a_failed_recompute_leaves_the_old_result_whole(client, job):
    job_id, job_dir = job
    post(client, job_id, [shop()])                                  # a good result first
    before = (job_dir / "place_events.csv").read_text(encoding="utf-8-sig")
    (job_dir / "input.mp4").unlink()                                # the video is gone, so rendering will fail

    r = post(client, job_id, [shop(door=[[0.1, 0.3], [0.1, 0.7]], inside=[0.3, 0.5])])

    assert r.status_code == 500
    assert (job_dir / "place_events.csv").read_text(encoding="utf-8-sig") == before      # not the half-made new one
    assert not list(job_dir.glob("tmp_*"))                                              # nothing left behind
    rec = main.jobs.get(job_id)
    assert [e["event"] for e in rec["places_result"]["events"]] == ["enter"] and rec["status"] == "done"
    assert (rec["phase"], rec["progress"], rec["recomputing"]) == ("", 100, False)


def test_a_bundle_made_from_the_old_result_is_not_kept(client, job):
    job_id, job_dir = job
    (job_dir / "results.zip").write_bytes(b"old bundle")
    assert post(client, job_id, [shop()]).status_code == 200
    assert not (job_dir / "results.zip").exists()                  # the next download builds a fresh one


def test_a_job_cannot_be_deleted_while_its_marks_are_applied(client, job):
    job_id, job_dir = job
    main.jobs.update(job_id, {"recomputing": True})
    assert client.delete(f"/api/jobs/{job_id}").status_code == 409
    assert job_dir.exists()


def test_the_saved_tracks_are_not_served_but_the_results_are(client, job):
    job_id, _ = job
    post(client, job_id, [shop()])
    assert client.get(f"/api/file/{job_id}/tracks.json").status_code == 404
    assert client.get(f"/api/file/{job_id}/place_events.csv").status_code == 200


def test_the_tracks_come_back_as_they_were_saved(tmp_path):
    processor.save_tracks(str(tmp_path), {"width": W, "height": H, "fps": FPS, "stride": 2, "last_fid": 9,
                                          "tracks": {7: [(0, 1.04, 2.06, 3.0, 4.0)]}, "person_of": {7: 3}})
    back = processor.load_tracks(str(tmp_path))
    assert back["tracks"] == {7: [(0, 1.0, 2.1, 3.0, 4.0)]}        # boxes are kept to a tenth of a pixel
    assert back["person_of"] == {7: 3}


# ── Who is who ────────────────────────────────────────────────
def lost_walker_job(job_id, job_dir, with_colours=True, second_clothes=((30, 30, 200), (20, 20, 20))):
    """Like the job above, but the walker is lost half way and picked up again under another track id."""
    import identity
    first = [(2 * i, 100 + 6 * i - 12, 60.0, 100 + 6 * i + 12, 120.0) for i in range(14)]        # up to x = 166, past the door
    second = [(2 * i, 100 + 6 * i - 12, 60.0, 100 + 6 * i + 12, 120.0) for i in range(18, 30)]    # picks up where they were heading

    def colours(shirt, trousers, frames):
        frame = np.full((H, W, 3), 120, np.uint8)
        frame[75:90, 100:124] = shirt
        frame[93:110, 100:124] = trousers
        s = identity.sample(frame, (100, 60, 124, 120), [])
        return [[f, *s] for f in frames]

    sigs = {1: colours((30, 30, 200), (20, 20, 20), range(0, 26, 6)), 2: colours(*second_clothes, range(36, 58, 6))}
    processor.save_tracks(str(job_dir), {"width": W, "height": H, "fps": FPS, "stride": 2, "last_fid": 89, "tracks": {1: first, 2: second},
                                         "signatures": sigs if with_colours else {}})


def test_a_lost_person_found_again_is_one_visitor_with_the_evidence_kept(client, job):
    job_id, job_dir = job
    lost_walker_job(job_id, job_dir)

    body = post(client, job_id, [shop()]).json()

    visitors = body["places_result"]["visitors"]
    assert [(v["label"], v["tracks"], v["joined"], v["uncertain"]) for v in visitors] == [("V001", [1, 2], 1, False)]
    assert visitors[0]["shirt"] == "#c81e1e" and visitors[0]["links"][0]["level"] == "confirmed"
    assert body["stats"]["people"] == 1
    audit = json.loads((job_dir / "identity.json").read_text(encoding="utf-8"))
    assert audit["enabled"] and audit["tracks"] == 2 and audit["visitors"] == 1 and audit["links"][0]["a"] == 1
    assert {e["person_id"] for e in body["places_result"]["events"]} == {1}


def test_someone_in_other_clothes_is_another_visitor(client, job):
    job_id, job_dir = job
    lost_walker_job(job_id, job_dir, second_clothes=((40, 160, 40), (235, 235, 235)))

    body = post(client, job_id, [shop()]).json()

    assert [v["label"] for v in body["places_result"]["visitors"]] == ["V001", "V002"] and body["stats"]["people"] == 2


def test_a_job_with_no_colour_samples_keeps_the_trackers_ids(client, job):
    job_id, job_dir = job
    lost_walker_job(job_id, job_dir, with_colours=False)

    body = post(client, job_id, [shop()]).json()

    assert body["places_result"]["visitors"] == [] and body["stats"]["people"] == 2
    assert json.loads((job_dir / "identity.json").read_text(encoding="utf-8"))["enabled"] is False


def test_events_name_the_trackers_track_not_a_cut_piece(client, job):
    job_id, job_dir = job
    lost_walker_job(job_id, job_dir)
    events = post(client, job_id, [shop()]).json()["places_result"]["events"]
    assert events and {e["track_id"] for e in events} <= {1, 2}


def test_a_video_that_cannot_be_replaced_leaves_the_old_result_whole(client, job, monkeypatch):
    """On Windows a file that a browser has open cannot be replaced: nothing must change, and nothing may be left behind."""
    job_id, job_dir = job
    post(client, job_id, [shop()])
    before = {name: (job_dir / name).read_bytes() for name in ("place_events.csv", "place_metrics.json", "identity.json", "annotated.mp4")}
    real = os.replace

    def refuse_video(src, dst):
        if Path(dst).name == "annotated.mp4":
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", refuse_video)
    monkeypatch.setattr(processor.time, "sleep", lambda s: None)

    r = post(client, job_id, [shop(door=[[0.1, 0.3], [0.1, 0.7]], inside=[0.3, 0.5])])

    assert r.status_code == 500 and "close it" in r.json()["detail"].lower()
    assert {name: (job_dir / name).read_bytes() for name in before} == before     # the old result, all of it
    assert not list(job_dir.glob("tmp_*"))


def test_tracks_saved_before_visitor_ids_load_with_no_signatures(tmp_path):
    processor.save_tracks(str(tmp_path), {"width": W, "height": H, "fps": FPS, "stride": 2, "last_fid": 9,
                                          "tracks": {1: [(0, 1.0, 2.0, 3.0, 4.0)]}, "person_of": {1: 5}})
    raw = json.loads((tmp_path / "tracks.json").read_text(encoding="utf-8"))
    del raw["signatures"]                                                       # as an older file has it
    (tmp_path / "tracks.json").write_text(json.dumps(raw), encoding="utf-8")
    back = processor.load_tracks(str(tmp_path))
    assert back["signatures"] == {} and back["person_of"] == {1: 5}
