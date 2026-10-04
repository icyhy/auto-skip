"""Whole-window OCR for automatic decisions; reuse engines and identical frames."""
import asyncio
import hashlib
import time
import re
from difflib import SequenceMatcher
from .core import author_name


class FastOCR:
    def __init__(self):
        self.engine=None
        self.fallback=None
        self.initialized=False
        self.last_digest=None
        self.last_text=""
        self.last_ms=0.0
        self.backend="Windows OCR"
        self.author_regions=[]
        self.author_cache={}

    def read(self,image):
        image=image.copy();image.thumbnail((1600,1600))
        digest=hashlib.sha256(image.tobytes()).digest()
        if digest==self.last_digest:self.last_ms=0;return self.last_text
        started=time.perf_counter()
        if not self.initialized:
            try:
                from winrt.windows.media.ocr import OcrEngine
                from winrt.windows.globalization import Language
                self.engine=OcrEngine.try_create_from_language(Language("zh-Hans-CN")) or OcrEngine.try_create_from_user_profile_languages()
            except (ImportError,OSError,RuntimeError):self.engine=None
            self.initialized=True
        if self.engine:
            text=asyncio.run(self._native(image))
        else:
            self.backend="RapidOCR"
            if self.fallback is None:
                from rapidocr_onnxruntime import RapidOCR
                self.fallback=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1,
                    det_limit_type="max",det_limit_side_len=1280,rec_batch_num=1)
            import numpy as np
            rows,_=self.fallback(np.asarray(image),use_cls=False)
            text="\n".join(row[1] for row in rows or [] if row[2]>=.8)
        text=re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])","",text)
        self.last_digest,self.last_text=digest,text
        self.last_ms=(time.perf_counter()-started)*1000
        return text

    def verify_author(self,image,author,blocked_names):
        """A near OCR match only requests a second reading; it never directly blocks."""
        current=author_name(author)
        expected={author_name(name) for name in blocked_names if author_name(name)}
        if not expected or current in expected or len(current)<6:return author
        possible={name for name in expected if SequenceMatcher(None,current,name).ratio()>=.82}
        if not possible:return author
        area=next((bounds for text,bounds in self.author_regions if author_name(text)==current),None)
        if area is None:return author
        image=image.copy();image.thumbnail((1600,1600))
        crop=image.crop(area)
        cache_key=(hashlib.sha256(crop.tobytes()).digest(),tuple(sorted(possible)))
        if cache_key in self.author_cache:return self.author_cache[cache_key]
        if self.fallback is None:
            from rapidocr_onnxruntime import RapidOCR
            self.fallback=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1,rec_batch_num=1)
        import numpy as np
        rows,_=self.fallback(np.asarray(crop),use_det=False,use_cls=False)
        verified=author
        for text,score in rows or []:
            name=author_name(text)
            if score>=.9 and name in possible:
                verified="@"+name;break
        self.author_cache[cache_key]=verified
        if len(self.author_cache)>32:self.author_cache.pop(next(iter(self.author_cache)))
        return verified

    async def _native(self,image):
        from winrt.windows.graphics.imaging import SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
        from winrt.windows.storage.streams import DataWriter
        # Import explicitly: WinRT loads these projections dynamically in a frozen app.
        import winrt.windows.foundation
        import winrt.windows.foundation.collections
        writer=DataWriter()
        bitmap=None
        try:
            writer.write_bytes(image.convert("RGBA").tobytes("raw","BGRA"))
            bitmap=SoftwareBitmap.create_copy_with_alpha_from_buffer(writer.detach_buffer(),BitmapPixelFormat.BGRA8,
                image.width,image.height,BitmapAlphaMode.IGNORE)
            result=await self.engine.recognize_async(bitmap)
            self.author_regions=[]
            for line in result.lines:
                if not line.text.strip().lstrip("·•.。'\"“”‘’ ").startswith(("@","＠")):continue
                boxes=[word.bounding_rect for word in line.words]
                if not boxes:continue
                bounds=(max(0,int(min(b.x for b in boxes))-3),max(0,int(min(b.y for b in boxes))-3),
                    min(image.width,int(max(b.x+b.width for b in boxes))+4),min(image.height,int(max(b.y+b.height for b in boxes))+4))
                self.author_regions.append((line.text,bounds))
            return "\n".join(line.text for line in result.lines)
        finally:
            if bitmap:bitmap.close()
            writer.close()
