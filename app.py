import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re

st.set_page_config(page_title="SMT Supervisor Agent", page_icon="🤖")
st.title("🤖 SMT Production Chat Agent")
st.caption("Enter updates naturally (e.g., 'Today we are producing 400 units for 719 CM')")

REQUIRED_COLUMNS = [
    "Line", "WO_No", "QTY", "Priority", "Description", 
    "Setup_Min", "Planned_End_Time", "Status", "Downtime_Min", "Tooling_Notes"
]

def sanitize_private_key(raw_key: str) -> str:
    """Extracts pure Base64 payload from mangled PEM string and rebuilds standard PEM format."""
    if not raw_key:
        return ""
    
    header = "-----BEGIN PRIVATE KEY-----"
    footer = "-----END PRIVATE KEY-----"
    
    if header in raw_key and footer in raw_key:
        # Extract content strictly between header and footer
        content = raw_key.split(header)[1].split(footer)[0]
        # Keep ONLY valid Base64 characters (A-Z, a-z, 0-9, +, /, =)
        clean_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', content)
        # Wrap Base64 payload into standard 64-character PEM lines
        chunks = [clean_b64[i:i+64] for i in range(0, len(clean_b64), 64)]
        pem_body = "\n".join(chunks)
        return f"{header}\n{pem_body}\n{footer}\n"
    
    return raw_key.replace("\\n", "\n")

@st.cache_resource
def get_gsheet_worksheet():
    """Authenticates with Google Sheets API using sanitized credentials."""
    info = dict(st.secrets["connections"]["gsheets"])
    
    if "private_key" in info:
        info["private_key"] = sanitize_private_key(str(info["private_key"]))
        
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_url(info["spreadsheet"]).sheet1

def load_data(sheet):
    """Loads sheet data safely into a Pandas DataFrame."""
    try:
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
    except Exception:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)

    if df.empty:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    else:
        df.columns = df.columns.astype(str).str.strip()
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                df[col] = ""
    return df

def save_data(sheet, df):
    """Overwrites the Google Sheet with updated DataFrame content."""
    sheet.clear()
    data = [df.columns.values.tolist()] + df.astype(str).values.tolist()
    sheet.update(data)

def update_schedule(user_input, sheet):
    df = load_data(sheet)
    text_upper = user_input.upper()
    
    # Extract Machine Line
    line = None
    for l in ["CM", "NPM", "MYDATA"]:
        if l in text_upper:
            line = l
            break
            
    # Extract Quantity
    qty_match = re.search(r'(\d+)\s*(?:UNITS|PCS|QUANTITY)?', user_input, re.IGNORECASE)
    qty = int(qty_match.group(1)) if qty_match else None
    
    # Extract Work Order Number
    wo_match = re.search(r'(?:WO|WORK ORDER|FOR|PART)?\s*([A-Z0-9\-]{3,})', text_upper)
    wo_no = wo_match.group(1) if wo_match else "719"

    if line and qty:
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
            
        save_data(sheet, df)
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
        
    sheet = get_gsheet_worksheet()
    updated_df, response = update_schedule(prompt, sheet)
    
    with st.chat_message("assistant"):
        st.markdown(response)
        st.dataframe(updated_df, use_container_width=True)
        
    st.session_state.messages.append({"role": "assistant", "content": response})
