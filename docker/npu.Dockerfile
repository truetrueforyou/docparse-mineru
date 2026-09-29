FROM quay.m.daocloud.io/ascend/vllm-ascend:v0.11.0

RUN apt-get update && \
    apt-get install -y fonts-noto-core fonts-noto-cjk fontconfig libgl1 libglib2.0-0 && \
    fc-cache -fv && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install -U pip -i https://mirrors.aliyun.com/pypi/simple && \
    python3 -m pip install 'mineru[core]>=3.4.0,<4' \
      numpy==1.26.4 opencv-python==4.11.0.86 \
      -i https://mirrors.aliyun.com/pypi/simple && \
    python3 -m pip cache purge

RUN TORCH_DEVICE_BACKEND_AUTOLOAD=0 /bin/bash -c "mineru-models-download -s modelscope -m all"

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
