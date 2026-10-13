# background_blur

Blurs the background of a video frame using the mask in its alpha channel
(see `person_mask`). numpy only, in 16-bit integers: only the soft edge of the
mask is blended, the rest is copied from the frame or from the blurred image.

## Node type: proc

## Node class name: BackgroundBlur

## Node name: background_blur

## Arguments

- `downscale`: factor by which the frame is reduced before blurring, an even
  number (default 4)
- `radius`: radius of each box blur pass, in pixels of the reduced frame (2, at
  most 4)
- `passes`: number of box blur passes (3)

## Input message

`Message[ImagePayload]` with an RGBA frame whose alpha channel is the person
mask (255 = person, 0 = background).

- Payload: `image` (`uint8`, `(height, width, 4)`) and `timestamp`. A frame
  without a mask, with alpha 255 everywhere, comes out unchanged.
- `meta`: no key is read. All of it is passed on.

## Output message

`Message[ImagePayload]`, one per input message.

- Payload: `image` is the frame with the background blurred and alpha 255;
  `width`, `height`, `depth` (4), `pixel_format` (`rgba`) and `timestamp` (the
  input one).
- `meta`: the input `meta` plus `ms_blur`, the milliseconds spent on the frame.
