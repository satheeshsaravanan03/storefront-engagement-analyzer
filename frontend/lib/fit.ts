export interface Size { w: number; h: number }
export interface Rect extends Size { x: number; y: number }

/* Where a picture of size `media` sits inside a `box` when it is shown whole (object-contain): centred, with bars
   at the sides or at the top and bottom when the shapes differ. The shop marks are drawn on this rectangle, not on
   the box, so they stay on the picture whatever shape the video has. Null until both sizes are known. */
export function fitRect(box: Size, media: Size): Rect | null {
  if (!(box.w > 0 && box.h > 0 && media.w > 0 && media.h > 0)) return null;
  const s = Math.min(box.w / media.w, box.h / media.h);
  const w = media.w * s;
  const h = media.h * s;
  return { x: (box.w - w) / 2, y: (box.h - h) / 2, w, h };
}
