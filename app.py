from openai import OpenAI
import streamlit as st
import streamlit_authenticator as stauth

import yaml
from yaml.loader import SafeLoader

from botpage import botpage

with open('./config.yml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

authenticator.login()

if st.session_state['authentication_status']:
    authenticator.logout()
    with st.sidebar:
        st.subheader("新建对话")
        for bot in ["全栈工程师", "哲学大师", "专家医生"]:
            st.button(bot)

        st.subheader("会话记录")

    if "bots" not in st.session_state:
        st.info(f"There is no bot defined.")
        st.stop()

    bot = next(b for b in st.session_state.bots if b.id == bot_id)
    if not bot:
        st.info(f"Can not find bot by id {bot_id}")
        st.stop()

    botpage(bot)

elif st.session_state['authentication_status'] is False:
    st.error('Username/password is incorrect')
elif st.session_state['authentication_status'] is None:
    st.warning('Please enter your username and password')