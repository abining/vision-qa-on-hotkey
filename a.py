

curl https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer a8417aa0-fb53-4f34-be47-3b145d176a50" \
  -d '{
    "model": "doubao-1-5-vision-pro-250328",
    "temperature": 0.2,
    "max_tokens": 4096,
    "dataset": {
      "id": "ds-20260227150910-ws7h7",
      "enable": true
    },
    "messages": [
      {
        "role": "system",
        "content": "你是一个擅长中文回答的视觉助手，基于关联的数据集内容回答问题。"
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "在合成数据时，为了避免模型生成的内容趋同，无法达到数据增广的目的，建议如何调整模型的“Temperature”（温度系数）参数？
A. 适当调高至1。0-1。2
B. 调低至0。1-0。3
C. 设置为0
D. 保持默认值0。7"
          }
        ]
      }
    ]
  }'




curl https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer a8417aa0-fb53-4f34-be47-3b145d176a50" \
  -d '{
    "model": "doubao-1-5-vision-pro-250328",
    "temperature": 0.2,
    "max_tokens": 4096,
    "dataset": {
      "id": "ds-20260227150910-ws7h7",
      "enable": true
    },
    "messages": [
      {
        "role": "system",
        "content": "你是一个擅长中文回答的视觉助手，基于关联的数据集内容回答问题。"
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "在合成数据时，为了避免模型生成的内容趋同，无法达到数据增广的目的，建议如何调整模型的“Temperature”（温度系数）参数？A. 适当调高至1。0-1。2B. 调低至0。1-0。3C. 设置为0D. 保持默认值0。7"
          }
        ]
      }
    ]
  }'




curl https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer a8417aa0-fb53-4f34-be47-3b145d176a50" \
  -d '{
    "model": "doubao-1-5-vision-pro-250328",
    "temperature": 0.2,
    "max_tokens": 4096,
    "dataset": {
      "id": "ds-20260227150910-ws7h7",
      "enable": true
    },
    "retrieval_log": true,
    "messages": [
      {
        "role": "system",
        "content": "你是一个擅长中文回答的视觉助手，基于关联的数据集内容回答问题。"
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "模型蒸馏中，“输出层蒸馏”类似于？"
          }
        ]
      }
    ]
  }'