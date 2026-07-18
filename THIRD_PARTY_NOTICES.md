# Third-party notices

## XDF compatibility

The built-in recorder's XDF chunk layout is compatible with the `xdfwriter` component from
LabStreamingLayer App-LabRecorder.

Copyright (c) 2012 Christian Kothe

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## edge-tts voice generation

The optional maintainer tool `tools/generate_voice_cues.py` uses `edge-tts` to generate the cached
Chinese voice assets. The `edge-tts` package is not imported by the experiment at runtime and is
not copied into this repository. It is available under the GNU Lesser General Public License v3.0:

https://github.com/rany2/edge-tts
