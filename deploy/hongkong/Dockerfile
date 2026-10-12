FROM python:3.12-slim
WORKDIR /app
# CPU wheels avoid shipping CUDA runtime libraries to this non-GPU server.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt transformers==4.46.3 safetensors
COPY run.py ./
COPY 后端代码 ./后端代码
COPY 前端代码 ./前端代码
COPY deploy/hongkong/start.py ./deploy/hongkong/start.py
RUN groupadd --gid 10001 editor && useradd --uid 10001 --gid editor --no-create-home editor \
 && mkdir -p /data/cache/huggingface/hub && chown -R editor:editor /data
USER editor
ENV HOST=0.0.0.0 PORT=8787 DATA_DIR=/data SEGMENTATION_MODEL_DIR=/models/slimsam SEGMENTATION_DEVICE=cpu SEGMENTATION_CPU_THREADS=1 HF_HOME=/data/cache/huggingface HF_HUB_CACHE=/data/cache/huggingface/hub XDG_CACHE_HOME=/data/cache HF_HUB_OFFLINE=1
EXPOSE 8787
CMD ["python", "deploy/hongkong/start.py"]
