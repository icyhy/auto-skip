"""Qt and native OCR runtime compatibility, using a synthetic image only."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QCoreApplication
from PIL import Image,ImageDraw,ImageFont
from autoskip.fast_ocr import FastOCR

app=QCoreApplication([])
image=Image.new("RGB",(700,180),"white")
ImageDraw.Draw(image).text((20,20),"@测试作者\n数码客观评测\n不要点击广告链接",font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",28),fill="black")
reader=FastOCR();text=reader.read(image)
assert "测试作者" in text and "数码客观评测" in text,text
print("Qt and Windows OCR synthetic image: PASS",reader.backend,round(reader.last_ms,1),"ms")
