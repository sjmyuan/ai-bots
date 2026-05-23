import streamlit as st
import time


def get_next_bot_id(db):
    """Get the next available bot ID using epoch seconds."""
    return int(time.time())


def add_bot(db, bot_data):
    """Add a new bot to MongoDB."""
    try:
        bot_data["id"] = get_next_bot_id(db)
        result = db.bots.insert_one(bot_data)
        st.session_state.refresh_bots = True
        return bot_data
    except Exception as e:
        st.error(f"添加机器人失败：{str(e)}")
        return None


def update_bot(db, bot_id, bot_data):
    """Update an existing bot in MongoDB."""
    try:
        result = db.bots.update_one({"id": bot_id}, {"$set": bot_data})
        st.session_state.refresh_bots = True
    except Exception as e:
        st.error(f"更新机器人失败：{str(e)}")


def delete_bot(db, bot_id):
    """Delete a bot and its associated sessions from MongoDB."""
    try:
        db.bots.delete_one({"id": bot_id})
        db.sessions.delete_many({"bot_id": bot_id})
        # TODO: Need to consider reset current session if the current bot is deleted
        st.session_state.refresh_bots = True
    except Exception as e:
        st.error(f"删除机器人失败：{str(e)}")


def show_bot_form(db, existing_bot=None):
    """Show form for adding or editing a bot."""
    with st.form(key=f"bot_form"):
        bot_name = st.text_input(
            "机器人名称", value=existing_bot.get("name", "") if existing_bot else ""
        )
        bot_prompt = st.text_area(
            "系统提示词",
            value=existing_bot.get("prompt", "") if existing_bot else "",
            height=200,
        )

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("保存")
        with col2:
            cancel = st.form_submit_button("取消")

        if submit and bot_name and bot_prompt:
            bot_data = {"name": bot_name, "prompt": bot_prompt}

            if existing_bot:
                update_bot(db, existing_bot["id"], bot_data)
                st.success(f"机器人 '{bot_name}' 已成功更新！")
                return True
            else:
                add_bot(db, bot_data)
                st.success(f"机器人 '{bot_name}' 已成功添加！")
                return True
        elif submit:
            st.error("机器人名称和系统提示词不能为空。")

        return cancel


def bot_management_page(db):
    """Display the bot management page."""
    st.title("机器人管理")

    if db is None:
        st.error("机器人管理需要数据库连接。")
        return

    if st.session_state.get("refresh_bots", False):
        st.session_state.refresh_bots = False
        st.rerun()

    # Initialize state variables if they don't exist
    if "edit_bot_id" not in st.session_state:
        st.session_state.edit_bot_id = None
    if "confirm_delete_id" not in st.session_state:
        st.session_state.confirm_delete_id = None
    if "show_add_form" not in st.session_state:
        st.session_state.show_add_form = False

    # Add new bot section
    if st.button("新增机器人", use_container_width=True):
        st.session_state.show_add_form = True
        st.session_state.edit_bot_id = None
        st.session_state.confirm_delete_id = None

    if st.session_state.show_add_form:
        st.subheader("新增机器人")
        if show_bot_form(db):
            st.session_state.show_add_form = False
            st.rerun()

    # List existing bots
    st.subheader("现有机器人")

    # Get bots from session state to ensure they're up to date
    bots = st.session_state.bots

    if not bots:
        st.info("暂无机器人，请新增一个机器人。")
    else:
        for bot in bots:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{bot['name']}**")
                with col2:
                    if st.button("编辑", key=f"edit_{bot['id']}"):
                        st.session_state.edit_bot_id = bot["id"]
                        st.session_state.show_add_form = False
                        st.session_state.confirm_delete_id = None
                        st.rerun()
                with col3:
                    if st.button("删除", key=f"delete_{bot['id']}"):
                        st.session_state.confirm_delete_id = bot["id"]
                        st.session_state.edit_bot_id = None
                        st.session_state.show_add_form = False
                        st.rerun()

                # Show delete confirmation
                if st.session_state.confirm_delete_id == bot["id"]:
                    st.warning(f"确定要删除 '{bot['name']}' 吗？")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("确认删除", key=f"confirm_{bot['id']}"):
                            delete_bot(db, bot["id"])
                            st.session_state.confirm_delete_id = None
                            st.success(f"机器人 '{bot['name']}' 已成功删除！")
                            st.rerun()
                    with col2:
                        if st.button("取消", key=f"cancel_{bot['id']}"):
                            st.session_state.confirm_delete_id = None
                            st.rerun()

                # Show edit form
                if st.session_state.edit_bot_id == bot["id"]:
                    st.subheader(f"编辑机器人：{bot['name']}")
                    if show_bot_form(db, bot):
                        st.session_state.edit_bot_id = None
                        st.rerun()

                st.divider()
