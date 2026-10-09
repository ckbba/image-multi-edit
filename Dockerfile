FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-segmentation.txt ./
RUN pip install --no-cache-dir -r requirements-segmentation.txt
COPY run.py ./
COPY 后端代码 ./后端代码
COPY 前端代码 ./前端代码
ENV HOST=0.0.0.0 PORT=8787 DATA_DIR=/data SEGMENTATION_MODEL_DIR=/models/slimsam
EXPOSE 8787
CMD ["python", "run.py"]
