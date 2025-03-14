import streamlit as st
import time

def get_next_bot_id(db):
    """Get the next available bot ID."""
    highest_bot = db.bots.find_one(sort=[("id", -1)])
    if highest_bot:
        return highest_bot["id"] + 1
    return 1

def add_bot(db, bot_data):
    """Add a new bot to MongoDB."""
    try:
        bot_data["id"] = get_next_bot_id(db)
        result = db.bots.insert_one(bot_data)
        st.session_state.refresh_bots = True
        return bot_data
    except Exception as e:
        st.error(f"Error adding bot to MongoDB: {str(e)}")
        return None

def update_bot(db, bot_id, bot_data):
    """Update an existing bot in MongoDB."""
    try:
        result = db.bots.update_one({"id": bot_id}, {"$set": bot_data})
        st.session_state.refresh_bots = True
    except Exception as e:
        st.error(f"Error updating bot in MongoDB: {str(e)}")

def delete_bot(db, bot_id):
    """Delete a bot from MongoDB."""
    db.bots.delete_one({"id": bot_id})
    st.session_state.refresh_bots = True

def show_bot_form(db, existing_bot=None):
    """Show form for adding or editing a bot."""
    with st.form(key=f"bot_form"):
        bot_name = st.text_input("Bot Name", value=existing_bot.get("name", "") if existing_bot else "")
        bot_prompt = st.text_area("Bot Prompt", value=existing_bot.get("prompt", "") if existing_bot else "", height=200)
        
        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("Save")
        with col2:
            cancel = st.form_submit_button("Cancel")

        if submit and bot_name and bot_prompt:
            bot_data = {
                "name": bot_name,
                "prompt": bot_prompt
            }
            
            if existing_bot:
                update_bot(db, existing_bot["id"], bot_data)
                st.success(f"Bot '{bot_name}' updated successfully!")
                return True
            else:
                add_bot(db, bot_data)
                st.success(f"Bot '{bot_name}' added successfully!")
                return True
        elif submit:
            st.error("Bot name and prompt are required.")
            
        return cancel

def bot_management_page(db):
    """Display the bot management page."""
    st.title("Bot Management")
    
    if db is None:
        st.error("Database connection is required for bot management.")
        return
    
    # Check if bots need refreshing
    if st.session_state.get("refresh_bots", False):
        # Fetch the current bots - this will happen in app.py initialize_session_state
        st.session_state.refresh_bots = False
        st.rerun()
    else:
        # Fetch the current bots
        bots = list(db.bots.find().sort("id", 1))
    
    # Initialize state variables if they don't exist
    if "edit_bot_id" not in st.session_state:
        st.session_state.edit_bot_id = None
    if "confirm_delete_id" not in st.session_state:
        st.session_state.confirm_delete_id = None
    if "show_add_form" not in st.session_state:
        st.session_state.show_add_form = False
    
    # Add new bot section
    if st.button("Add New Bot", use_container_width=True):
        st.session_state.show_add_form = True
        st.session_state.edit_bot_id = None
        st.session_state.confirm_delete_id = None
    
    if st.session_state.show_add_form:
        st.subheader("Add New Bot")
        if show_bot_form(db):
            st.session_state.show_add_form = False
            st.rerun()
    
    # List existing bots
    st.subheader("Existing Bots")
    
    # Get bots from session state to ensure they're up to date
    bots = st.session_state.bots
    
    if not bots:
        st.info("No bots available. Add a new bot to get started.")
    else:
        for bot in bots:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{bot['name']}**")
                with col2:
                    if st.button("Edit", key=f"edit_{bot['id']}"):
                        st.session_state.edit_bot_id = bot["id"]
                        st.session_state.show_add_form = False
                        st.session_state.confirm_delete_id = None
                        st.rerun()
                with col3:
                    if st.button("Delete", key=f"delete_{bot['id']}"):
                        st.session_state.confirm_delete_id = bot["id"]
                        st.session_state.edit_bot_id = None
                        st.session_state.show_add_form = False
                        st.rerun()
                
                # Show delete confirmation
                if st.session_state.confirm_delete_id == bot["id"]:
                    st.warning(f"Are you sure you want to delete '{bot['name']}'?")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Yes, Delete", key=f"confirm_{bot['id']}"):
                            delete_bot(db, bot["id"])
                            st.session_state.confirm_delete_id = None
                            st.success(f"Bot '{bot['name']}' deleted successfully!")
                            st.rerun()
                    with col2:
                        if st.button("Cancel", key=f"cancel_{bot['id']}"):
                            st.session_state.confirm_delete_id = None
                            st.rerun()
                
                # Show edit form
                if st.session_state.edit_bot_id == bot["id"]:
                    st.subheader(f"Edit Bot: {bot['name']}")
                    if show_bot_form(db, bot):
                        st.session_state.edit_bot_id = None
                        st.rerun()
                
                st.divider()
