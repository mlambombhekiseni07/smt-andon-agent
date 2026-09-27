import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import re

st.set_page_config(page_title="SMT Supervisor Agent", page_icon="🤖")
st.title("🤖 SMT Production Chat Agent")
st.caption("Enter updates naturally (e.g., 'Today we are producing 400 units for 719 CM')")

# Required column structure
REQUIRED_COLUMNS = [
    "Line", "WO_No", "QTY", "Priority", "Description", 
    "Setup_Min", "Planned_End_Time", "Status", "Downtime_Min", "Tooling_Notes"
]

# Fetch secrets and clean private key escape characters (\n) dynamically
raw_secrets = dict(st.secrets["connections"]["gsheets"])
if "private_key" in raw_secrets:
    # Converts literal '\\n' strings into actual linebreaks expected by RSA
    raw_secrets["private_key"] = raw_secrets["private_key"].replace("\\n", "\n")

# Connect using the cleaned secrets dictionary
conn = st.connection("gsheets", type=GSheetsConnection, **raw_secrets)

def load_data():
    """Loads sheet data safely."""
    try:
        df = conn.read(ttl=0)
    except Exception:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)

    if df is None or df.empty:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    else:
        df.columns = df.columns.astype(str).str.strip()
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                df[col] = ""
    return df

def update_schedule(user_input, df):
    text_upper = user_input.upper()
    
    # Identify Machine Line
    line = None
    for l in ["CM", "NPM", "MYDATA"]:
        if l in text_upper:
            line = l
            break
            
    # Extract Quantity
    qty_match = re.search(r'(\d+)\s*(?:UNITS|PCS|QUANTITY)?', user_input, re.IGNORECASE)
    qty = int(qty_match.group(1)) if qty_match else None
    
    # Extract Work Order
    wo_match = re.search(r'(?:WO|WORK ORDER|FOR|PART)?\s*([A-Z0-9\-]{3,})', text_upper)
    wo_no = wo_match.group(1) if wo_match else "719"

    if line and qty:
        # Match existing row
        mask = (df["Line"].astype(str).str.upper() == line) & (df["WO_No"].astype(str) == str(wo_no))
        
        if mask.any():
            df.loc[mask, "QTY"] = qty
            df.loc[mask, "Status"] = "Running"
            msg = f"✅ Updated **{line}** | Work Order **{wo_no}** to QTY **{qty}**."
        else:
            new_row = pd.DataFrame([{
                "Line": line,
                "WO_No": str(wo_no),
                "QTY": qty,
                "Priority": len(df[df["Line"] == line]) + 1,
                "Description": f"WO-{wo_no}",
                "Setup_Min": 30,
                "Planned_End_Time": "16:00",
                "Status": "Running",
                "Downtime_Min": 0,
                "Tooling_Notes": ""
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            msg = f"✅ Added new job to **{line}** | Work Order **{wo_no}** | QTY **{qty}**."
            
        # Write back to Google Sheets
        conn.update(data=df)
        return df, msg
    else:
        return df, "⚠️ Could not parse line or quantity. Example: *'CM line job 719 quantity 400'*"

# Interface
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Type schedule update..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    df = load_data()
    updated_df, response = update_schedule(prompt, df)
    
    with st.chat_message("assistant"):
        st.markdown(response)
        st.dataframe(updated_df, use_container_width=True)
        
    st.session_state.messages.append({"role": "assistant", "content": response})
