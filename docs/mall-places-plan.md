# Mall places: shop-level metrics from one fixed camera

This note is the plan for the **Mall places** mode: upload one video from a fixed mall camera, mark the shops once, and get per-shop and cross-shop numbers. The existing **Stand attention** mode is unchanged; the user picks the mode on the upload page.

## Goal and scope

From one video, report for each shop who **entered**, **exited**, **stopped in front** or **passed by**, and which people visited more than one shop.

Version 1 measures movement, not attention. Today's "facing" test means *facing the camera* (nose and both eyes visible plus a frontal-face detector). That is only a valid proxy for looking at a shop when the camera sits at the shop front. In a corridor view most people never face the camera, so glance and look are left for a later version.

### Camera

A **fixed** camera, high or at corridor level, that sees the floor and the shop doors. Best: center-top, angled down, shops on both sides. Worst: eye level in a crowd, where people in front hide the feet of those behind.

## Metrics

| Level | Metrics |
|---|---|
| Per shop | unique people entered, total entries, exits, re-entries, average time inside (when seen), stopped at the front, passed by |
| Across shops | only A, only B, A and B, A not B, B not A, direct moves A to B, ordered journeys |

Overlaps are computed twice: for people who **entered**, and for people **interested** (entered or stopped at the front).

### Definitions

- **Entered**: the person's feet cross the door line **heading toward the pin**, then either stay in the shop area for `stay_sec` (default 2.5 s) or vanish at the door or in the shop area. A step in and straight back out is a **peek** and is not counted. Walking on past the shop area, walking along the door, or leaving the picture is not an entry.
- **Exited**: the feet cross the door line heading away from the pin (also for someone first seen inside, or first seen on the line and then clearly walking away from it).
- **Stopped at front**: one unbroken stretch of at least `stop_sec` (default 3 s) with the feet inside the front area and moving slowly. Separate short pauses do not add up.
- **Passed by**: feet in the front area, but never stopped and never entered.
- **Not a visitor**: a track that is there for nearly the whole video (at least 10 s and 90% of it) and never moves is a mannequin or poster the detector took for a person. It is ignored everywhere.

## How it works

1. **Marking** (per video, on one frame, in the browser). For every shop: two clicks for the **door line** on the floor, one click for the **inside pin**, and an optional polygon for the **floor area in front**. The pin does three jobs: it says which side is in, which way people walk into the shop (door middle to pin), and how deep the shop area is. The editor shades exactly that area, so what is drawn is what the analysis uses. Points can be dragged, undone, and zoomed into with a magnifier. Coordinates are fractions of the frame (0 to 1), so they hold at any resolution. They travel in the existing `config` JSON of `POST /api/analyze`.
2. **Detection and tracking**: a plain person detector (`yolov8m.pt` by default, no pose needed) at a large `imgsz`, and ByteTrack with a longer track memory. While tracking, a few colour samples of each person's shirt and trousers are kept (see **Visitor ids**). Frames are skipped so the analysis runs at about 12 fps.
3. **Feet, not bodies.** Only the feet point is tested against the marks. A body in front of a shop covers the shop's pixels without being in it. Marks are drawn on the floor for the same reason.
4. **Hidden feet.** When the box bottom is hidden by a crowd or the frame edge, the feet are estimated from the head: per video we fit how tall a standing person looks at each row of the picture, then solve for the feet row. The estimate is adjusted by that person's own usual size. Events that rely on estimated feet get a lower confidence.
5. **Door logic.** A signed distance to the door line gives the side. A buffer band around the line, a tenth of the person's height wide, stops jitter from counting twice, a new side must hold for two observations, and points more than half a body height (and never more than a quarter of the door's length, since a door seen end-on is short on screen) beyond the ends of the line are ignored. A crossing only counts if the person is heading toward the pin (this is what tells someone walking along a wall from someone walking in, whatever the camera angle). "Staying" means staying in the shop area; a person who vanishes counts only if they vanish at the door or in the shop area and not at the edge of the picture. Real doors hide people before their feet reach the line, so a track that ends within two bands of the line after walking straight at it also counts, with a lower confidence. People often appear at, or vanish into, a doorway where the shop hides them, so two cases count on less evidence and get a lower confidence: a track that ends with its feet clearly past the line, and a track that starts on the line and then walks clearly away from it.
6. **Visitor ids.** The tracker's id is only a temporary label; each person gets one visitor number (V001, ...) for the whole video, from `backend/identity.py` (below).
7. **Journeys.** The visitor number across shops in the video feeds the overlap, transition and journey counts in `backend/journeys.py`.

## Visitor ids

Mall mode only: Stand attention and `reid.py` are untouched, and no face or hair is matched here.

**What is kept.** While the video is read, a colour sample (HSV histogram and median colour of the shirt and of the trousers) is taken about four times a second for each tracked person, but only when they are at least 32 px tall, not cut by the left or right edge, and not covered by anybody else. The samples are saved with the tracks (`tracks.json`), so identity can be run again offline and when the marks are adjusted.

**What is done** (`backend/identity.py`, run inside `analyze_places_job`):

1. **Undo swaps.** Where two or more people overlapped, the people who carry on afterwards are matched again with the people who were there before (colours, position against where each was heading, change of walking). The tracker's own pairing stands unless another one is clearly cheaper, each swap is judged on its own, and the pieces are joined crosswise so nobody is left fragmented. A knot of people is only touched when every person in it can be judged: with one unaccounted for, a pairing of the others can be wrong.
2. **Join lost people.** A person who disappears and appears again under a new track id is joined when the colours match over the whole piece and at the point where one ends and the other starts, and the new piece starts where the old one was heading (the tolerance grows with the gap, in body heights). The best one-to-one pairing is chosen where leaving a piece unpaired is cheap at the picture's edge, at a shop door and at the ends of the video, and dear in the middle of the walkway. A person who goes into a shop and comes out of the same door up to 5 minutes later can be joined too, on colours alone.
3. **Confidence.** A join is *confirmed* only when the colours, the movement and the margin are all clear; the margin is how much the pairing is worth over the next best arrangement of the pieces competing for these two, and a piece without colours counts as a rival. Anything weaker is a *candidate*: it is kept as evidence and the visitor is marked **uncertain**, but nothing is merged. A wrong merge is worse than a missed one.
4. **Visitors.** Confirmed joins chain pieces into visitors, numbered V001... by first appearance. The visitor's colours (median shirt and trousers) are shown on the Visitors card, with the reason for every join. `identity.json` keeps every join and every swap with its evidence.

`memory_sec` (default 8 s, 1 to 60) is how long a lost person is waited for. With more than 4000 pieces nothing is joined (the work grows with the square of the number of pieces).

**How it is measured** (`backend/idmetrics.py`, run against CAVIAR's hand labels): IDF1 (share of boxes carrying the right id), ID switches, extra fragments of a person, ids that carry two people, and for every confirmed join whether it was right (both pieces follow the same labelled person). Frames in which nothing was found count as misses. The **ceiling** is IDF1 if every matched box carried the right id; it is below 1 because the detector misses people.

### Results

Five labelled corridor clips (384x288), the detector and tracker as they run in the application. The thresholds were set on the first clip only; the others were not used for tuning.

| Clip | People | IDF1 tracker ids | IDF1 visitors | Ceiling | Switches | Fragments | Ids with 2+ people | Confirmed joins |
|---|---|---|---|---|---|---|---|---|
| TwoEnterShop2cor (64 s) | 16 | 0.652 | 0.654 | 0.850 | 23 to 22 | 21 to 20 | 9 to 9 | 2 (1 right, 0 wrong) |
| TwoEnterShop1cor (66 s) | 12 | 0.769 | 0.770 | 0.873 | 14 to 13 | 10 to 9 | 5 to 5 | 2 (1 right, 0 wrong) |
| OneLeaveShop1cor (12 s) | 6 | 0.842 | 0.842 | 0.916 | 4 to 4 | 3 to 3 | 2 to 2 | 0 |
| OneStopNoEnter1cor (29 s) | 3 | 0.933 | 0.933 | 0.933 | 0 | 0 | 0 | 0 |
| OneStopMoveEnter1cor (64 s) | 19 | 0.792 | 0.805 | 0.925 | 24 to 23 | 15 to 14 | 5 to 5 | 1 (1 right, 0 wrong) |
| WalkByShop1cor (94 s) | 17 | 0.583 | 0.583 | 0.863 | 38 to 38 | 27 to 27 | 9 to 9 | 0 |
| **All six** | 73 | mean 0.762 | mean 0.764 | | 103 to 100 | 76 to 73 | 30 to 30 | 5 (3 right, 0 wrong, 2 not checkable) |

What this says, plainly:

- The visitor ids are never worse than the tracker's ids on these clips and there were no wrong joins, but the gain is small: most of the distance to the ceiling is people the tracker swapped in knots of three or more, which are not undone because there is not enough evidence to do it safely.
- Colour is a weak cue at this size. On hand-drawn boxes, the best of six colour descriptions we tried told two different people apart only about 88% of the time (AUC 0.88), and the one in use was the best of them. A person can look 50% unlike themselves between the near and far end of the corridor. Better pictures should help; this has not been measured because no labelled footage at that quality is available here.
- Door returns (a person who went into a shop and came back out of the same door) were suggested five times in all, at colour matches of 84 to 89%, and every one was a different person: three on the first clip (all removed once the colours were also checked where the two pieces meet) and two on other clips (kept as candidates, nothing merged). Colour alone cannot confirm them in this footage.
- A first version cut every track at every doubtful overlap and tried to join the pieces again. It lowered IDF1 on every clip (0.842 to 0.687 on one), because cutting only pays when the pieces are joined correctly again. The version above never fragments anyone.
- Shop entries are only checked on TwoEnterShop2cor, the clip the marks were drawn on: 4 of its 5 labelled entries found, each within 0.6 s of the label, none false, and the same events with visitor ids as with tracker ids. The other clips have labelled entries at doors that were not marked, so their entry counts say nothing about accuracy.
- Clips without labels: a stock mall corridor (22 s) gave 23 tracks, 20 visitors, one candidate and the same shop events as before; a handheld 2560x1440 street clip gave 66 tracks and 56 visitors. That one is not a fixed camera, it has mannequins in shop windows, and checking the joins by eye showed one confirmed join where a track had changed from a mannequin to a person near its end, so numbers there are for information only.

## Accuracy approach

Automatic accuracy comes first. There is no human review step in version 1; a confidence score is kept per event for debugging only.

- Measure with event precision, recall and F1 (within about 1 to 2 s, same shop and direction), count accuracy per shop, IDF1 and ID switches for identity, and exact-match journeys.
- Targets to confirm on real footage, not promises: about 95% automatic for entered and exited on good footage (98% is the goal to measure); IDF1 of 90% or more for "visited both" in light to medium crowds.
- Proving 98% needs a few hundred labelled entries. One miss in 50 entries is already 98%.

## Constraints

- **Hardware**: CPU only (no NVIDIA GPU). Analysis runs on about every 2nd to 5th frame. A cloud GPU is an option for the final accuracy runs.
- **Privacy**: mall footage is personal data of people who did not consent. Face matching is not run in mall mode and no face snapshots are saved. Set a retention limit before real CCTV is used.
- **Input safety**: the zone data and settings come from the browser, so the backend validates them, and the detector model name is limited to a fixed list (a model file is a pickle).
- **No login yet**: more important once real CCTV is uploaded.

## Phases

| Phase | Work | Where |
|---|---|---|
| 0 | Fix definitions (this document), choose and label test clips | `docs/`, local test clips |
| 1 | Marking screen, validated zone format, zone overlay in the annotated video | `frontend/components/PlaceMarker.tsx`, `backend/places.py` |
| 2 | Mall mode: feet estimate, door and front logic, `place_events.csv` | `backend/places.py`, `backend/processor.py` |
| 3 | Metrics module and API fields | `backend/journeys.py`, `backend/main.py` |
| 4 | Results view: shop cards, overlap table, journeys, events | `frontend/components/PlaceResults.tsx` |
| 5 | Validation harness and tuning loop, accuracy report | `backend/tests/`, local test clips |
| 6 | Login, retention limit, real-footage tuning | open |

Decision taken while building phase 1: the frame for marking is captured in the browser from the chosen file, so a large video is not uploaded twice. If the browser cannot decode the file the user is told to use an H.264 MP4.

Added after the first real runs: the tracked people are saved with each job (`tracks.json`), so **Adjust marks** on the results page applies new marks in seconds without detecting anyone again (`POST /api/jobs/{id}/recompute`). Jobs saved before this change have no `tracks.json` and cannot be adjusted.

## Outputs of a mall-places job

| File | Contents |
|---|---|
| `annotated.mp4` | tracked people with IDs, feet (yellow when estimated), event badges, a small clock and counter. The shops are not burned in: the page draws them over the video, where they can be switched off. The live preview while a job runs works the same way (the backend sends the frame with the people on it, the page draws the shops), and the Jobs list plays this video when a job is opened. The video link carries the file's time stamp, so a video written again after new marks is never played from the browser's cache |
| `tracks.json` | the tracked people and their colour samples, kept so the marks can be adjusted later |
| `identity.json` | every swap undone and every join (confirmed or candidate) with its evidence: colours, gap, movement, margin |
| `place_events.csv` | one row per event: person, track, event, shop, time, frame, confidence, estimated feet, reason |
| `place_metrics.json` | per-shop numbers, overlaps, transitions and journeys |

## Tests

pytest (see `backend/tests/`, run with `python -m pytest` in `backend`): geometry and zone validation (including hostile payloads), height model and feet estimate, door crossing (peek, stay, vanish, exit, jitter, line ends, doorway cases), front area timing, mannequins, overlap and journey counts, and a simulated-camera test with walkers on a perspective height line that checks the events. Identity has its own tests (`test_identity.py`): colour samples and when they are refused, finding overlaps, undoing swaps (with and without colours, knots with someone who cannot be judged, two swaps judged separately, a track cut twice), joining lost people (same and different clothes, wrong place, too long, rivals with and without colours, the colours where two pieces meet, chains, door returns), numbering of visitors, a speed guard with hundreds of look-alikes, and the scoring tool itself. A real-footage check runs the whole pipeline on a clip with a known answer.

## Status

Phases 1 to 4 are built, the marking editor has been redesigned, and the real pipeline has been run end to end through the browser, including adjusting marks on a finished job. Phase 5 has started: there is now one real clip with CAVIAR's hand labels (below) and a test that keeps it honest, but that is far too little to say anything about 95% or 98%.

| Clip | Camera | Known answer | Result |
|---|---|---|---|
| Veo clip c01 (7.9 s) | fixed, high, shops across the far wall | one person enters the boutique at about 5.2 s, nobody enters the bookstore | one entry at 5.5 s, bookstore 0 |
| Stock clip, corridor (22 s), my marks | fixed, eye level, shops on both sides | nobody enters; people walk past with their bodies over the shop windows | 0 entries, 4 people passing one shop; a mannequin that was counted as passing is now ignored |
| CAVIAR TwoEnterShop2cor (64 s, 384x288), a user's marks | fixed, eye level, two doors drawn 23 and 39 px long on screen | 5 people enter the shop (the labels give when each stops being visible: 9.8, 14.9, 15.2, 20.1, 43.6 s) and 7 leave | 4 of the 5 entries found, each within 0.6 s of the label, none false (0 found before the last round of fixes); 1 of the 7 exits. The missed entry is the second of two people walking in together |
| Same corridor clip as above, a user's marks | a line drawn from the Boss window out to the frame corner, pin on the walkway floor | nobody enters | 3 false entries with the first version of the rules, 1 with the current rules: people walking along the wall, or out of the picture, no longer count. The one left is a person walking toward a pin that was placed on the walkway floor, which by those marks is the inside |

Known limits:

- Two clips with one entry between them prove the plan works mechanically, not that it is accurate. The next step is a few hundred labelled entries from longer fixed-camera footage.
- Speed on a CPU (i5-10500) with the defaults is about 8 to 14 times the video length. Several jobs at once will compete for CPU and memory: there is no concurrency limit, and none for upload size (both were already true for stand mode).
- Exits are found far less often than entries: most people leaving a shop appear at the door with no track before it, so there is no crossing to see. Two people walking in together are counted once when the tracker joins them.
- Adjusting marks renders the video inside the request. For a short clip that is seconds; it grows with the length of the video, and behind the public tunnel's 100 s limit a very long video would report a failure while the server finishes. The old result is kept if it fails.
- The marks still decide the result. A door line drawn across a walkway, or a pin placed on the walkway instead of inside the shop, will count people walking there. The editor shows the shop area so this is visible, but it cannot know where the real shop is.
- A door at the very edge of the picture cannot be counted: a track that ends at the edge is taken as having left the picture.
- A person who first appears on the door line and steps off it needs a clear step (twice the dead band) to count as an exit. A person who stands on the threshold and is then lost is not counted as entering unless the feet are past the line by half the dead band.
- Stop time is the longest single stretch per track; if the tracker re-labels someone in the middle of a stop, the two halves are not added together.
- The browser must be able to decode the video to mark the shops (H.264 MP4 is safe).
- Visitor ids: a knot of three or more people the tracker swapped is left as the tracker had it, so ids that carry two people (30 over the six clips) are not reduced. Visitor numbers can change when the marks are adjusted, because the door lines decide where a person may vanish and return. A person seen for only two analysed frames still gets a visitor number. A mannequin seen for less than 10 s (the fixture rule needs 10 s and 90% of the video) is counted as a person: one in the stock corridor clip and at least two in the handheld street clip. People smaller than 32 px have no colour samples and are never joined to anyone. Linking is off above 4000 pieces of track.
- Jobs analysed before the marks could be adjusted have no `tracks.json`: they cannot be adjusted, and if an older version of the analysis made them, their `annotated.mp4` has that version's shop marks burned in (the page then draws the new ones over them). Upload the video again to get a clean one.
- Adjusting the marks runs the identity step again; it takes well under a second for a 94 s clip and about 6 s for 2000 tracks.
- Shop names that are not in Latin script show as `?` on the annotated video (OpenCV's built-in font). The CSV, the metrics file and the web pages show them correctly.
