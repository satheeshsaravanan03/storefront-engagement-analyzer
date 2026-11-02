# How we find faces in a video and match them to registered people

This note explains, in plain words, how the app goes from an uploaded exhibition video to a card that says "this viewer is Sneha Kapoor, here is her email and phone". It has two parts: how we find the viewers in the video, and how we match a viewer's face to the people who registered.

Everything here only works for people who registered and agreed to be recognised. Nobody is looked up on the internet by this feature (Google Lens is a separate, older feature and is untouched).

---

## Part 1: Finding the viewers in the video

### The video never goes to the face model

This surprises people, so it's worth saying first. The face-matching model never watches the video. The video is handled by the original analysis step, and face matching only starts after that step has finished and saved some pictures.

### Step by step

1. **Read the video frame by frame.** The backend opens the file with OpenCV and walks through the frames one after another.

2. **Find the people.** Each frame goes through a YOLOv8 pose model. It does not look at faces. It looks for whole bodies and marks key points on them: head, shoulders, elbows and so on. That is enough to tell where a person is and which way they are roughly turned.

3. **Follow each person.** A tracker called ByteTrack gives every person an ID and keeps that ID as they move from frame to frame. Without this we would count the same visitor hundreds of times. Sometimes the tracker loses someone and gives them a new ID when they come back. A small helper (`reid.py`) uses colour of clothes and hair to stitch those IDs back together. It is only used for merging IDs. It plays no part in recognising who anyone is.

4. **Decide who was really watching.** From the pose data we work out which people were facing the stand and for how long. Those are the "engaged viewers" in the results table.

5. **Save a snapshot of each viewer.** For every engaged viewer we keep one picture, saved as `captures/person_N.jpg` inside that job's folder. That picture is the only thing the face step ever sees.

So the video gives us a short list of people and one photo each. Everything after this works on those photos.

---

## Part 2: Matching a face to a registered person

Matching runs automatically once a video finishes. It works on faces only. Clothes, background, hairstyle and posture are ignored on purpose, because a registration photo taken last year and a snapshot taken today will rarely look alike in those.

### The registry

Registered people live in `backend/registry/profiles.json`: name, email, phone, role, company, and the file name of their photo. For now this is a small static list. Later it will be synced from the real registration system. The photos are kept out of git because they are personal data.

### What happens to a photo

Both the registered photo and the viewer snapshot go through the same three steps.

**1. Find the face.** A small detector called YuNet looks for a face and returns a box plus five landmarks: the two eyes, the nose and the two corners of the mouth. If it finds several faces it picks the biggest and most confident one. Faces narrower than 28 pixels are thrown away, because there is not enough detail to compare. Tiny crops are enlarged first so the detector has something to work with.

**2. Straighten the face.** Using those five landmarks, the face is rotated and scaled so the eyes and mouth always land in the same spot. This removes most of the difference between a tilted head and a straight one, or a close-up and a far-away shot.

**3. Turn the face into numbers.** A model called SFace reads the straightened face and produces a list of 128 numbers, called an embedding. It was trained so that different photos of the same person give similar lists and different people give different lists. Think of it as a fingerprint of the face structure, not a picture.

The registered photos are processed once and cached, so each new video only needs the snapshot side.

### Comparing two faces

We compare the viewer's 128 numbers with every registered person's 128 numbers using cosine similarity. It gives a score from about 0 (nothing alike) to 1 (identical). That score is the percentage shown on the cards.

### Deciding what to show

| Result | When | What you see |
|---|---|---|
| **Matched** | Best score is 45% or more, and it beats the second-best person by at least 5 points | The registered profile card |
| **Possible** | Best score is 36% or more but one of the two conditions above fails | The profile with a "please confirm" note |
| **Unmatched** | Best score is below 36% | A card saying the viewer is not in the registered list |
| **No face** | The face is too small, turned away or blurred | A card saying there is no clear face |

The 5-point lead matters. If two registered people both score high, the system would rather say "possible" than guess wrong.

---

## How well does it work, and where does it struggle?

On the jobs we tested, real matches scored between roughly 54% and 77%, while viewers who were not in the registry scored 36% or lower. Running the same photo against itself gives 100%, which is a useful sanity check.

Things to keep in mind:

- **The thresholds are not magic.** They come from OpenCV's published guidance plus a small sample of our own videos. With more real exhibition footage they should be re-tuned.
- **Only one snapshot per viewer is used.** If that one frame is a bad angle, the match suffers even if the person looked straight at the camera ten seconds later.
- **Hard cases:** faces turned more than about 45 degrees, faces under about 60 pixels wide, masks, sunglasses and poor light. In these cases the usual result is "unmatched" or "possible", not a wrong name, but a wrong name is not impossible.
- **Old photos lower the score.** A registration photo from years ago, or in a very different style, will score lower than a fresh one.
- **A person can be split in two.** If the tracker gives one visitor two IDs and the merge step misses it, they show up as two viewers.
- **Staff should confirm.** The score is a similarity, not a probability, so a human should check matches before acting on them.

## What we would improve next

- Compare several frames per viewer instead of one, and use the best or the average. This is the biggest gain for the least work.
- Swap in a stronger model such as ArcFace. Only the `embed` function in `backend/faces.py` has to change.
- Put a staff login in front of the Leads and match pages before this goes on the public site, since it shows names and contact details.

## Where the code is

- `backend/faces.py`: detection, embedding, scoring and the thresholds
- `backend/main.py`: runs matching after each job and exposes the registry endpoints
- `backend/registry/profiles.json`: the static list of registered people
- `frontend/components/MatchedLeads.tsx`: the cards in Jobs
- `frontend/app/leads/page.tsx`: the Registered leads page
