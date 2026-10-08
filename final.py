import streamlit as st
import fitz
import pandas as pd
import re
import requests


# =========================================================
# OPENROUTER API KEY
# =========================================================

OPENROUTER_API_KEY = "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"


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def extract_text_from_pdf(uploaded_file):

    try:

        pdf_bytes = uploaded_file.read()

        with fitz.open(
            stream=pdf_bytes,
            filetype="pdf"
        ) as doc:

            text = ""

            for page in doc:
                text += page.get_text() + "\n"

        return text

    except Exception as e:

        st.error(
            f"Failed to read PDF: {str(e)}"
        )

        return None


# =========================================================
# PARSE UPI TRANSACTIONS
# =========================================================

def parse_transactions(text):

    if not text:
        return pd.DataFrame()

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    transactions = []

    # -----------------------------------------------------
    # DATE FORMAT
    # -----------------------------------------------------

    date_pattern = re.compile(
        r"^(\d{2}-[A-Za-z]{3}-\d{4})$"
    )

    amount_pattern = re.compile(
        r"^[\d,]+\.\d{2}$"
    )

    # -----------------------------------------------------
    # FIND TRANSACTION BLOCKS
    # -----------------------------------------------------

    i = 0

    while i < len(lines):

        # Transaction format:
        #
        # 03-Apr-2026
        # 03-Apr-2026
        # Description
        # Amount
        # Balance

        if (
            date_pattern.match(lines[i])
            and
            i + 1 < len(lines)
            and
            date_pattern.match(lines[i + 1])
        ):

            transaction_date = lines[i]

            # Skip Date and Value Date
            i += 2

            block = []

            # -------------------------------------------------
            # COLLECT TRANSACTION BLOCK
            # -------------------------------------------------

            while i < len(lines):

                # Next transaction starts here
                if (
                    date_pattern.match(lines[i])
                    and
                    i + 1 < len(lines)
                    and
                    date_pattern.match(lines[i + 1])
                ):
                    break

                block.append(lines[i])

                i += 1

            # -------------------------------------------------
            # FIND NUMERIC VALUES
            # -------------------------------------------------

            numeric_values = []

            for line in block:

                if amount_pattern.match(line):

                    numeric_values.append(line)

            # Need at least:
            #
            # Transaction Amount
            # Balance

            if len(numeric_values) < 2:
                continue

            # Last number = Balance
            balance_text = numeric_values[-1]

            # Second-last number = Transaction Amount
            amount_text = numeric_values[-2]

            try:

                amount = float(
                    amount_text.replace(",", "")
                )

                balance = float(
                    balance_text.replace(",", "")
                )

            except ValueError:

                continue

            # -------------------------------------------------
            # GET DESCRIPTION
            # -------------------------------------------------

            description_lines = []

            for line in block:

                # Don't include amounts
                if amount_pattern.match(line):
                    continue

                upper_line = line.upper()

                # Ignore statement headers
                if (
                    "STATEMENT OF ACCOUNT" in upper_line
                    or "CUSTOMER ID" in upper_line
                    or "ACCOUNT NO" in upper_line
                    or "STATEMENT PERIOD" in upper_line
                    or "OPENING BALANCE" in upper_line
                    or "TOTAL DEBIT" in upper_line
                    or "TOTAL CREDIT" in upper_line
                    or "CLOSING BALANCE" in upper_line
                    or "REGISTERED OFFICE" in upper_line
                    or upper_line.startswith("PAGE ")
                ):
                    continue

                description_lines.append(line)

            description = " ".join(
                description_lines
            )

            description = re.sub(
                r"\s+",
                " ",
                description
            ).strip()

            # -------------------------------------------------
            # SAVE TRANSACTION
            # -------------------------------------------------

            transactions.append(
                {
                    "Date": transaction_date,
                    "Description": description,
                    "Transaction Amount": amount,
                    "Balance": balance
                }
            )

        else:

            i += 1

    # -----------------------------------------------------
    # CREATE DATAFRAME
    # -----------------------------------------------------

    df = pd.DataFrame(transactions)

    if df.empty:
        return df

    # -----------------------------------------------------
    # DATE
    # -----------------------------------------------------

    df["Date"] = pd.to_datetime(
        df["Date"],
        format="%d-%b-%Y",
        errors="coerce"
    )

    # -----------------------------------------------------
    # NUMERIC VALUES
    # -----------------------------------------------------

    df["Transaction Amount"] = pd.to_numeric(
        df["Transaction Amount"],
        errors="coerce"
    )

    df["Balance"] = pd.to_numeric(
        df["Balance"],
        errors="coerce"
    )

    # -----------------------------------------------------
    # REMOVE INVALID ROWS
    # -----------------------------------------------------

    df = df.dropna(
        subset=[
            "Date",
            "Transaction Amount",
            "Balance"
        ]
    )

    # -----------------------------------------------------
    # DETERMINE DEBIT / CREDIT
    # -----------------------------------------------------
    #
    # Opening balance from your statement
    #

    previous_balance = 60325.08

    debits = []
    credits = []

    for _, row in df.iterrows():

        current_balance = row["Balance"]

        amount = row["Transaction Amount"]

        # -----------------------------------------------
        # BALANCE DECREASED
        # -----------------------------------------------
        #
        # Money went OUT
        #
        # Therefore = Debit
        #

        if current_balance < previous_balance:

            debits.append(amount)
            credits.append(0.0)

        # -----------------------------------------------
        # BALANCE INCREASED
        # -----------------------------------------------
        #
        # Money came IN
        #
        # Therefore = Credit
        #

        elif current_balance > previous_balance:

            debits.append(0.0)
            credits.append(amount)

        else:

            debits.append(0.0)
            credits.append(0.0)

        previous_balance = current_balance

    df["Debits"] = debits

    df["Credits"] = credits

    # Amount = spending amount
    #
    # Only Debit transactions are spending.

    df["Amount"] = df["Debits"]

    return df


# =========================================================
# CATEGORIES
# =========================================================

DEFAULT_CATEGORIES = {

    "Food": [
        "zomato",
        "swiggy",
        "food",
        "zepto",
        "bigbasket",
        "dominos",
        "pizza",
        "kfc",
        "mcdonalds",
        "burger king",
        "starbucks"
    ],

    "Travel": [
        "uber",
        "ola",
        "rapido",
        "travel",
        "zingbus",
        "redbus",
        "fuel",
        "petrol",
        "diesel",
        "automobiles"
    ],

    "Shopping": [
        "amazon",
        "flipkart",
        "meesho",
        "myntra",
        "shopping",
        "v mart",
        "dmart",
        "croma",
        "reliance digital",
        "ajio"
    ],

    "Entertainment": [
        "netflix",
        "spotify",
        "hotstar",
        "cinema",
        "cinemas",
        "pvr",
        "inox",
        "story tv",
        "storytv"
    ],

    "Bills": [
        "electricity",
        "water",
        "gas",
        "bill",
        "airtel broadband",
        "broadband",
        "maintenance"
    ],

    "Recharge": [
        "recharge",
        "airtel",
        "jio",
        "bharti airtel"
    ],

    "Google Payment": [
        "google play",
        "google india",
        "google"
    ],

    "Insurance": [
        "insurance",
        "star health",
        "lic"
    ],

    "Health": [
        "pharmacy",
        "doctor",
        "health",
        "medicine",
        "medical",
        "hospital"
    ],

    "Friends & Family": [
        "gift",
        "friend",
        "family"
    ],

    "Salary": [
        "salary"
    ],

    "Wallet / Payment Service": [
        "mobikwik"
    ],

    "Merchant Payment": [
        "bharatpe",
        "merchant"
    ],

    "Others": []
}


# =========================================================
# CATEGORIZE TRANSACTIONS
# =========================================================

def categorize_transactions(df, categories):

    if df.empty:
        return df

    def get_category(description):

        desc = str(description).lower()

        for category, keywords in categories.items():

            for keyword in keywords:

                if keyword in desc:

                    return category

        return "Others"

    df["Category"] = df["Description"].apply(
        get_category
    )

    return df


# =========================================================
# MONTHLY SPENDING
# =========================================================

def get_monthly_spending(df):

    monthly = (
        df.groupby(
            df["Date"].dt.to_period("M")
        )["Debits"]
        .sum()
        .sort_index()
    )

    return monthly


# =========================================================
# CATEGORY SPENDING
# =========================================================

def get_category_spending(df):

    category = (
        df.groupby("Category")["Debits"]
        .sum()
        .sort_values(
            ascending=False
        )
    )

    return category


# =========================================================
# AI FINANCIAL ADVICE
# =========================================================

def generate_ai_recommendations(df):

    if df.empty:

        return "No transaction data available."

    # ONLY DEBITS = SPENDING

    total_spent = df["Debits"].sum()

    transaction_count = len(df)

    monthly_spending = (
        get_monthly_spending(df)
    )

    category_spending = (
        get_category_spending(df)
    )

    # -----------------------------------------------------
    # MONTHLY INFORMATION
    # -----------------------------------------------------

    monthly_text = ""

    for month, amount in monthly_spending.items():

        monthly_text += (
            f"{month}: ₹{amount:,.2f}\n"
        )

    # -----------------------------------------------------
    # CATEGORY INFORMATION
    # -----------------------------------------------------

    category_text = ""

    for category, amount in category_spending.items():

        percentage = 0

        if total_spent > 0:

            percentage = (
                amount / total_spent
            ) * 100

        category_text += (
            f"{category}: "
            f"₹{amount:,.2f} "
            f"({percentage:.2f}%)\n"
        )

    # -----------------------------------------------------
    # PROMPT
    # -----------------------------------------------------

    prompt = f"""
You are a personal finance analysis assistant.

Analyze the user's actual UPI spending data.

IMPORTANT RULES:

1. Use ONLY the information provided below.
2. Do not invent transactions.
3. Do not invent income or salary.
4. Do not assume the user's financial situation.
5. Use actual ₹ amounts.
6. Calculate percentages when useful.
7. Give practical budgeting and saving suggestions.
8. Do not recommend specific stocks or risky investments.
9. Keep the advice simple and easy to understand.

ACTUAL TRANSACTION DATA:

Total spending:
₹{total_spent:,.2f}

Number of transactions:
{transaction_count}

MONTHLY SPENDING:

{monthly_text}

CATEGORY SPENDING:

{category_text}

Provide the answer in exactly this structure:

### Personalized Financial Tips

**1. Monthly Spending Pattern**

Explain the user's monthly spending pattern using the actual data.

**2. Highest Spending Categories**

Mention the two highest spending categories using their actual ₹ amounts and percentages.

**3. Savings and Budgeting Suggestions**

Give three practical suggestions based on the actual spending.

### Key Takeaway

Give a short summary of the user's spending behavior.

Remember:
- Do not invent numbers.
- Do not assume salary.
- Use ₹ for amounts.
"""

    # -----------------------------------------------------
    # API
    # -----------------------------------------------------

    if (
        not OPENROUTER_API_KEY
        or OPENROUTER_API_KEY ==
        "YOUR_NEW_OPENROUTER_API_KEY"
    ):

        return (
            "OpenRouter API key is not configured. "
            "Please add your new API key."
        )

    url = (
        "https://openrouter.ai/api/v1/chat/completions"
    )

    headers = {

        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json"
    }

    payload = {

        "model": "openrouter/auto",

        "messages": [

            {
                "role": "user",
                "content": prompt
            }

        ],

        "temperature": 0.2
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code == 200:

            result = response.json()

            return result[
                "choices"
            ][0][
                "message"
            ][
                "content"
            ]

        else:

            return (
                f"OpenRouter error "
                f"{response.status_code}: "
                f"{response.text}"
            )

    except Exception as e:

        return (
            f"AI request failed: {str(e)}"
        )


# =========================================================
# MAIN APPLICATION
# =========================================================

def main():

    st.set_page_config(
        page_title="UPI Analyzer Pro",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 UPI Analyzer Pro")

    st.subheader(
        "Smart Financial Insights"
    )

    # -----------------------------------------------------
    # PDF UPLOAD
    # -----------------------------------------------------

    uploaded_file = st.file_uploader(
        "Upload UPI Statement PDF",
        type=["pdf"]
    )

    if uploaded_file is None:

        st.info(
            "Please upload your UPI statement PDF."
        )

        return

    # -----------------------------------------------------
    # EXTRACT PDF
    # -----------------------------------------------------

    with st.spinner(
        "Extracting text from PDF..."
    ):

        raw_text = extract_text_from_pdf(
            uploaded_file
        )

    if not raw_text:

        st.error(
            "Could not extract text from the PDF."
        )

        return

    # -----------------------------------------------------
    # PARSE TRANSACTIONS
    # -----------------------------------------------------

    with st.spinner(
        "Parsing transactions..."
    ):

        df = parse_transactions(
            raw_text
        )

    if df.empty:

        st.error(
            "No transactions found. "
            "Please check the PDF format."
        )

        st.write(
            "### Extracted Text Preview"
        )

        st.text(
            raw_text[:5000]
        )

        return

    # -----------------------------------------------------
    # CATEGORIZE
    # -----------------------------------------------------

    df = categorize_transactions(
        df,
        DEFAULT_CATEGORIES
    )

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    st.success(
        f"Processed {len(df)} transactions!"
    )

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    # IMPORTANT:
    # Total spent = Debit only

    total_spent = df["Debits"].sum()

    number_transactions = len(df)

    total_credits = df["Credits"].sum()

    start_date = df["Date"].min()

    end_date = df["Date"].max()

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Total Spent",
            f"₹{total_spent:,.2f}"
        )

    with col2:

        st.metric(
            "Money Received",
            f"₹{total_credits:,.2f}"
        )

    with col3:

        st.metric(
            "Transactions",
            number_transactions
        )

    with col4:

        st.metric(
            "Period",
            f"{start_date.strftime('%d %b %Y')} - "
            f"{end_date.strftime('%d %b %Y')}"
        )

    # -----------------------------------------------------
    # TABS
    # -----------------------------------------------------

    tab1, tab2, tab3 = st.tabs(
        [
            "📄 Transactions",
            "📈 Spending Analysis",
            "🤖 AI Financial Advice"
        ]
    )

    # =====================================================
    # TAB 1
    # =====================================================

    with tab1:

        st.write(
            "### Transaction History"
        )

        display_df = df.sort_values(
            by="Date",
            ascending=False
        )

        display_df = display_df[
            [
                "Date",
                "Description",
                "Debits",
                "Credits",
                "Balance",
                "Category"
            ]
        ]

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # -------------------------------------------------
        # DOWNLOAD CSV
        # -------------------------------------------------

        csv_data = display_df.to_csv(
            index=False
        )

        st.download_button(
            label="⬇️ Download Transactions CSV",
            data=csv_data,
            file_name="upi_transactions.csv",
            mime="text/csv"
        )

    # =====================================================
    # TAB 2
    # =====================================================

    with tab2:

        # -------------------------------------------------
        # MONTHLY SPENDING
        # -------------------------------------------------

        st.write(
            "### 📅 Monthly Spending"
        )

        monthly_spending = (
            get_monthly_spending(df)
        )

        monthly_chart = (
            monthly_spending.copy()
        )

        monthly_chart.index = (
            monthly_chart.index.astype(str)
        )

        st.bar_chart(
            monthly_chart
        )

        # -------------------------------------------------
        # MONTHLY TABLE
        # -------------------------------------------------

        st.write(
            "#### Monthly Spending Details"
        )

        monthly_table = pd.DataFrame(
            {
                "Month":
                    monthly_spending.index.astype(str),

                "Spending":
                    monthly_spending.values
            }
        )

        monthly_table["Spending"] = (
            monthly_table["Spending"]
            .map(
                lambda x:
                f"₹{x:,.2f}"
            )
        )

        st.dataframe(
            monthly_table,
            use_container_width=True,
            hide_index=True
        )

        # -------------------------------------------------
        # CATEGORY SPENDING
        # -------------------------------------------------

        st.write(
            "### 🏷 Category-wise Spending"
        )

        category_spending = (
            get_category_spending(df)
        )

        st.bar_chart(
            category_spending
        )

        # -------------------------------------------------
        # CATEGORY TABLE
        # -------------------------------------------------

        st.write(
            "#### Category Spending Details"
        )

        category_table = pd.DataFrame(
            {
                "Category":
                    category_spending.index,

                "Spending":
                    category_spending.values
            }
        )

        if total_spent > 0:

            category_table[
                "Percentage"
            ] = (
                category_table["Spending"]
                / total_spent
                * 100
            )

        else:

            category_table[
                "Percentage"
            ] = 0

        category_table["Spending"] = (
            category_table["Spending"]
            .map(
                lambda x:
                f"₹{x:,.2f}"
            )
        )

        category_table["Percentage"] = (
            category_table["Percentage"]
            .map(
                lambda x:
                f"{x:.2f}%"
            )
        )

        st.dataframe(
            category_table,
            use_container_width=True,
            hide_index=True
        )

    # =====================================================
    # TAB 3
    # =====================================================

    with tab3:

        st.write(
            "### 🤖 Personalized Financial Advice"
        )

        st.info(
            "AI advice is generated from your "
            "actual spending, monthly spending "
            "and category-wise transactions."
        )

        with st.spinner(
            "Analyzing your spending and generating advice..."
        ):

            insights = (
                generate_ai_recommendations(df)
            )

        st.markdown(
            insights
        )


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    main()