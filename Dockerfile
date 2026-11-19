FROM python:3.12-slim
# INSTALL_MODEL=1 (bawaan): ikut memasang torch CPU + transformers agar model IndoBERT
# bisa dipasang hanya dengan mengisi env MODEL_REPO. Isi 0 untuk image ringan
# khusus mesin aturan (sekitar 150 MB, bukan sekitar 1,3 GB).
ARG INSTALL_MODEL=1
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app
COPY --chown=user requirements.txt requirements-model.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt \
 && if [ "$INSTALL_MODEL" = "1" ]; then \
      pip install --no-cache-dir --user torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
      && pip install --no-cache-dir --user -r requirements-model.txt; \
    fi
COPY --chown=user app.py rules_engine.py triage_core.py ./
EXPOSE 7860
# start-period panjang: mode model mengunduh dan memanaskan model saat start.
HEALTHCHECK --interval=60s --timeout=5s --start-period=300s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=4)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
