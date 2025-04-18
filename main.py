import os,logging
from fastapi import FastAPI,File,UploadFile,HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from detector import LicensePlateDetector
from ocr_reader import OCRReader
logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger=logging.getLogger(__name__)
app=FastAPI(title="License Plate Recognition API",description="API for detecting and recognizing license plates from images",version="1.0.0")
detector=LicensePlateDetector(model_path="best.pt")
ocr=OCRReader()
@app.post("/lpr")
async def recognize_license_plate(file:UploadFile=File(...)):
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400,detail="File is not an image")
        contents=await file.read()
        cropped_plate=detector.detect_and_crop(contents)
        # write the cropped plate to a file for debugging
        if cropped_plate is None:
            return JSONResponse(status_code=200,content={"error":"License plate not detected or unreadable"})
        plate_text=ocr.read_text(cropped_plate)
        print("plate_text",plate_text)
        if not plate_text:
            return JSONResponse(status_code=200,content={"error":"License plate not detected or unreadable"})
        plate_text=''.join(ch for ch in plate_text if ch.isalnum()).upper()
        return {"plate_text":plate_text}
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return JSONResponse(status_code=500,content={"error":"Error processing the image"})
if __name__=="__main__":
    uvicorn.run("main:app",host="0.0.0.0",port=8000,reload=True)