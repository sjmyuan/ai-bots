# Import necessary libraries
import os
import time
from openai import OpenAI
import streamlit as st
import streamlit_authenticator as stauth
import logging

import yaml
from yaml.loader import SafeLoader
from botpage import botpage
from bot_management import bot_management_page

from streamlit.runtime.caching import cache_resource, cache_data
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

@cache_resource(ttl=600)
def get_db(mongo_uri, mongo_db):
    """Get the MongoDB database."""
    client = MongoClient(mongo_uri)
    return client[mongo_db]

def fetch_user_sessions(db, username, skip=0, limit=50):
    """Fetch sessions for the current user from MongoDB."""
    return list(
        db.sessions.find({"user": username})
        .sort("create_time", -1)
        .skip(skip)
        .limit(limit)
    )

def fetch_bots(db):
    """Fetch all bots from MongoDB."""
    return list(db.bots.find().sort("id", 1))

def initialize_bots(db, config_bots):
    """Initialize bots from MongoDB or create from config if none exist."""
    bots = fetch_bots(db)
    if not bots and config_bots:
        # Insert config bots into MongoDB if the collection is empty
        for bot in config_bots:
            db.bots.insert_one(bot)
        return config_bots
    return bots

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to create a new session
def create_new_session(username, bot_id):
    """Create a new session for the user with the specified bot."""
    return {
        "id": int(time.time()),
        "user": username,
        "create_time": datetime.now(timezone.utc),
        "name": None,
        "bot_id": bot_id,
        "messages": [],
    }

# Function to set the current session
def set_current_session(session):
    """Set the current session in the Streamlit session state."""
    st.session_state.current_session = session

def load_config(config_file):
    """Load configuration from a file."""
    try:
        with open(config_file) as file:
            return yaml.load(file, Loader=SafeLoader)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_file}")
    except yaml.YAMLError as e:
        logger.error(f"Error parsing configuration file: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading configuration: {e}")
    return None

def initialize_session_state(config, db):
    """Initialize session state variables."""
    # Initialize models from config
    if "models" not in st.session_state or len(st.session_state.models) != len(config["models"]):
        st.session_state.models = config["models"]
    
    # Initialize bots from MongoDB or fallback to config
    if db is not None:
        # Always set refresh_bots to False to avoid infinite refreshes
        refresh_needed = st.session_state.get("refresh_bots", False)
        if "bots" not in st.session_state or refresh_needed:
            st.session_state.bots = initialize_bots(db, config.get("bots", []))
            st.session_state.refresh_bots = False
    elif "bots" not in st.session_state:
        st.session_state.bots = config.get("bots", [])
    
    if "bot_sessions" not in st.session_state:
        st.session_state.bot_sessions = [] if db is None else fetch_user_sessions(db, st.session_state["name"])

    # Get the initial bot and model
    try:
        init_bot = next(b for b in st.session_state.bots)
        init_model = next(m for m in st.session_state.models)
    except StopIteration:
        logger.error("No bots or models found in the configuration.")
        st.info("There is no bot or model available.")
        st.stop()

    # Check if there are any bots or models
    if not init_bot:
        st.info("There is no bot")
        st.stop()

    if not init_model:
        st.info("There is no model")
        st.stop()

    if "current_session" not in st.session_state:
        st.session_state.current_session = create_new_session(st.session_state["name"], init_bot["id"])
    if "current_model" not in st.session_state:
        st.session_state.current_model = init_model
    if "current_page" not in st.session_state:
        st.session_state.current_page = "chat"
    # Ensure refresh_bots is defined
    if "refresh_bots" not in st.session_state:
        st.session_state.refresh_bots = False

def set_page(page_name):
    """Set the current page in the session state."""
    st.session_state.current_page = page_name

# Set the page configuration
st.set_page_config(
    "AI Bots", page_icon="https://images.shangjiaming.com/bio-photo.jpeg"
)

# Load the configuration from the environment variable
config = load_config(os.getenv("CONFIG_FILE"))
if not config:
    st.error("Failed to load configuration. Please check the CONFIG_FILE environment variable.")
    st.stop()

# Initialize the authenticator
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

# Perform authentication
authenticator.login()

# Check the authentication status
if st.session_state["authentication_status"]:
    # Log out the user
    authenticator.logout()

    db = None
    if os.getenv("MONGO_URI"):
        db = get_db(os.getenv("MONGO_URI"), "ai-bots")
    else:
        logger.warning("MONGO_URI environment variable is not set. User sessions will not be fetched from the database.")
    
    # Ensure bots and models are loaded
    initialize_session_state(config, db)
    
    # Navigation
    with st.sidebar:
        st.markdown("## Navigation")
        if st.session_state.current_page == "manage_bots":
            if st.button("Chat", use_container_width=True, 
                        type="primary" if st.session_state.current_page == "chat" else "secondary"):
                set_page("chat")

        if st.session_state.current_page == "chat":
            # Model selection
            selected_model = st.selectbox(
                "选择模型",
                st.session_state.models,
                next(
                    index
                    for index, value in enumerate(st.session_state.models)
                    if value["id"] == st.session_state.current_model["id"]
                ),
                lambda m: m["name"],
            )

            # Handle custom model input
            if selected_model["id"] == -1:
                custom_model_name = st.text_input("输入模型名称")
                selected_model["name"] = custom_model_name
                selected_model["model"] = custom_model_name
                st.session_state.current_model = selected_model
            else:
                st.session_state.current_model = selected_model
            
            # New conversation buttons
            st.subheader("新建对话")
            for bot in st.session_state.bots:
                st.button(
                    bot["name"],
                    on_click=set_current_session,
                    args=(create_new_session(st.session_state["name"], bot["id"]),),
                    use_container_width=True,
                )
            
            # Manage Bots button
            if st.button("Manage Bots", use_container_width=True,
                        type="primary" if st.session_state.current_page == "manage_bots" else "secondary"):
                set_page("manage_bots")
            
            # Session history buttons
            st.subheader("会话记录")

            # Group sessions by date
            grouped_sessions = {}
            for session in st.session_state.bot_sessions:
                date = session["create_time"].strftime("%Y-%m-%d")
                if date not in grouped_sessions:
                    grouped_sessions[date] = []
                grouped_sessions[date].append(session)

            # Display sessions grouped by date
            for date in sorted(grouped_sessions.keys(), reverse=True):
                st.markdown(f"### {date}")
                for session in grouped_sessions[date]:
                    st.button(
                        session["name"],
                        key=session["id"],
                        on_click=set_current_session,
                        args=(session,),
                        disabled=session["id"] == st.session_state.current_session["id"],
                        use_container_width=True,
                    )

            if db is not None:
                if st.button("Load more", use_container_width=True):
                    skip = len(st.session_state.bot_sessions)
                    additional_sessions = fetch_user_sessions(db, st.session_state["name"], skip=skip)
                    st.session_state.bot_sessions.extend(additional_sessions)
    
    # Display the appropriate page based on current_page
    if st.session_state.current_page == "chat":
        botpage(db)
    elif st.session_state.current_page == "manage_bots":
        bot_management_page(db)

# Handle authentication errors
elif st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
elif st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
