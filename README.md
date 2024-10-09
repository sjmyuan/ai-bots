# AI Bots

AI Bots is a simple platform that allows you to define your own OpenAI-compatible chatbot and chat with the AI bots.

## Creating a config file

The config file is based on the config file of [Streamlit-Authenticator](https://github.com/mkhorasani/Streamlit-Authenticator?tab=readme-ov-file#3-creating-a-config-file)

You just need to append the bots section to the config file

```yaml
bots:
  - id: 1 # bot id
    api_key: "" # api key
    base_url: "" # the base url of OpenAI-compatible platform, for example https://dashscope.aliyuncs.com/compatible-mode/v1
    model: "" # model name
    name: "" # bot name
    description: "" # bot description
    prompt: "" # bot prompt
```

## Run the application with Docker

```sh
docker run -d -e CONFIG_FILE=/app/config.yml -v <path to config file>:/app/config.yml -p 8501:8501 sjmyuan/ai-bots:v0.0.5
```