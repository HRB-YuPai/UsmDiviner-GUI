Preferred: use a shared build.
Recommended layout: `bin/ffmpeg` plus sibling `lib/*.so*` files.
Keeping `ffmpeg` and `*.so*` in the same folder can also work, but `bin/` + `lib/` matches upstream shared packages best.
UsmDiviner will auto-detect it on Linux arm64.
