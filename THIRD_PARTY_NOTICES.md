# Reference and attribution

Auto Skip's typed JEV category questions, direct TypeSafe request shape, frame/text deduplication and OCR reuse design reference:

- [goutoujunshi-jev-chat](https://github.com/shengjidaguai-china/goutoujunshi-jev-chat), commit `d19fd84305b5baa2f4b0f1147f177b163fef70a0`.
- Relevant modules: `integrations/jev_windows/core/jev_client.py`, `core/questions.py`, `app/ocr.py`, `app/worker.py`, and `integrations/jev_mac/jev.py`.
- Upstream Windows integration credits [jev-chat-windows](https://github.com/jev-chat/jev-chat-windows).
- Protocol checked against [TypeSafe API reference](https://docs.typesafe.ai/api).

The implementation in this repository adapts the approach to video category filtering and retains the following source acknowledgements. The referenced authors do not endorse Auto Skip.

## MIT License notices

Copyright (c) 2026 powerycy

Copyright (c) 2026 rezoch340 and the jev-chat contributors

Portions Copyright (c) 2026 Finderchangchang and the jev-chat contributors
(Jev 聊天助手, https://github.com/jev-chat/jev-chat-jarvis)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
