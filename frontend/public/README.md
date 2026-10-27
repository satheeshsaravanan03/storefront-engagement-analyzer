# /public/ folder — Static Assets

## How to add your real annotated video

Place your annotated output video (from the Colab pipeline) in this folder.

### File names expected:

| Filename              | Tab shown on website     |
|-----------------------|--------------------------|
| `demo-retail.mp4`     | Retail Store tab         |
| `demo-event.mp4`      | Event Gate tab           |
| `demo-corridor.mp4`   | Corridor tab             |

### Steps:

1. Run the Colab notebook on your test video (Cell 10 or Cell 11)
2. Download the output: `output/real_video_output.mp4` or `output/uploaded_output.mp4`
3. Rename it to `demo-retail.mp4`
4. Copy it into THIS folder (`crowdvision/frontend/public/demo-retail.mp4`)
5. Restart `npm run dev` (or it hot-reloads automatically)
6. Open http://localhost:3000 — click the "Retail Store" tab in the demo section

### If you only have one video:

Copy the same file three times:
```
copy output_video.mp4 demo-retail.mp4
copy output_video.mp4 demo-event.mp4
copy output_video.mp4 demo-corridor.mp4
```

All three tabs will show the same annotated video — that is fine for the demo.

### Why does it work?

Next.js serves everything in `/public/` as static files at the root URL.
So `public/demo-retail.mp4` becomes `http://localhost:3000/demo-retail.mp4`.
The `<video src="/demo-retail.mp4">` in `app/page.tsx` loads it directly.

### File size note:

Keep videos under 50 MB for smooth browser playback.
If your video is larger, compress it first:
```
ffmpeg -i input.mp4 -vcodec libx264 -crf 28 demo-retail.mp4
```


ffmpeg -i input_video.mp4 -vf "format=yuv420p" -vcodec libx264 -acodec aac -movflags +faststart final.mp4

do this for browser play video 