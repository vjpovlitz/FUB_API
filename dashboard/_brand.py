"""Dana Capital Realty branding for the FUB dashboard.

Palette + type pulled from danacapitalrealty.com: brand blue #005dcf on navy,
Saira (display) + Montserrat (body). Use:

    from _brand import apply_brand, header, style_fig, PLOTLY_COLORWAY, BLUE_SCALE
    st.set_page_config(...); apply_brand(); header("Title", "subtitle")
    st.plotly_chart(style_fig(fig), width="stretch")
"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

# --- palette (danacapitalrealty.com) ---
NAVY_DEEP = "#02101d"
NAVY = "#083d6e"
BLUE = "#005dcf"        # primary brand blue
BLUE_BRIGHT = "#1c82ff"
BLUE_LIGHT = "#69acff"
BLUE_PALE = "#bdddfa"
INK = "#1d1d1d"
MIST = "#f3f5f8"
CLOUD = "#f0f5fa"
WHITE = "#ffffff"

# Categorical palette + a light→navy blue scale for continuous color.
PLOTLY_COLORWAY = [BLUE, BLUE_BRIGHT, NAVY, BLUE_LIGHT, "#0068e8", BLUE_PALE]
BLUE_SCALE = [[0.0, BLUE_PALE], [0.5, BLUE_BRIGHT], [1.0, NAVY]]

_ASSETS = Path(__file__).resolve().parent / "assets"


def _logo_b64() -> str:
    p = _ASSETS / "logo.png"
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Saira:wght@500;600;700&family=Montserrat:wght@400;500;600&display=swap');

html, body, .stApp, [class*="css"], [data-testid="stMarkdownContainer"],
input, textarea, select, button {{ font-family: 'Montserrat', sans-serif; }}
h1, h2, h3, h4, h5 {{
    font-family: 'Saira', 'Montserrat', sans-serif;
    letter-spacing: .4px; font-weight: 600; color: {NAVY};
}}

/* strip the default Streamlit chrome for a cleaner, non-stock look */
[data-testid="stToolbar"], [data-testid="stDecoration"],
#MainMenu, footer, header[data-testid="stHeader"] {{ display: none !important; }}

.block-container {{ padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 1300px; }}
.stApp {{ background: linear-gradient(180deg, {WHITE} 0%, {CLOUD} 100%); }}

/* branded header banner */
.dcr-header {{
    display: flex; align-items: center; gap: 18px;
    padding: 18px 26px; margin: 0 0 22px 0; border-radius: 14px;
    background: linear-gradient(120deg, {NAVY_DEEP} 0%, {NAVY} 58%, {BLUE} 150%);
    box-shadow: 0 10px 28px rgba(8, 61, 110, .20);
}}
.dcr-logo {{ height: 52px; width: auto; }}
.dcr-title {{
    font-family: 'Saira', sans-serif; font-size: 1.6rem; font-weight: 700;
    color: {WHITE}; letter-spacing: .6px; line-height: 1.1; margin: 0;
}}
.dcr-sub {{ font-family: 'Montserrat', sans-serif; font-size: .86rem; color: {BLUE_PALE}; margin-top: 3px; }}

/* metric cards */
[data-testid="stMetric"] {{
    background: {WHITE}; border: 1px solid #e6edf6; border-left: 4px solid {BLUE};
    border-radius: 12px; padding: 14px 16px 12px 16px;
    box-shadow: 0 2px 12px rgba(8, 61, 110, .06);
}}
[data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; }}
[data-testid="stMetricLabel"] p {{
    color: #5b6b7e; font-weight: 600; text-transform: uppercase;
    letter-spacing: .5px; font-size: .72rem;
}}

/* ===== liquid-glass sidebar ===== */
[data-testid="stSidebar"] {{
    background: linear-gradient(198deg, rgba(2,16,29,.94) 0%, rgba(8,61,110,.82) 100%);
    -webkit-backdrop-filter: blur(22px) saturate(165%);
    backdrop-filter: blur(22px) saturate(165%);
    border-right: 1px solid rgba(255,255,255,.08);
    box-shadow: 6px 0 34px rgba(2,16,29,.30);
}}
[data-testid="stSidebar"] * {{ font-family: 'Montserrat', sans-serif; color: rgba(255,255,255,.85); }}
[data-testid="stSidebarContent"] {{ padding-top: .2rem; }}

/* brand logo (st.logo) pinned at top of the glass */
[data-testid="stLogo"] {{
    height: 38px; width: auto; margin: 16px 10px 8px 16px;
    filter: drop-shadow(0 2px 7px rgba(0,0,0,.40));
}}

/* nav links -> glass pills */
[data-testid="stSidebarNav"] {{ padding: 4px 6px 2px 6px; }}
[data-testid="stSidebarNav"] ul {{ gap: 2px; }}
[data-testid="stSidebarNavLink"] {{
    border-radius: 11px; padding: 9px 12px; margin: 2px 4px;
    border: 1px solid transparent; transition: all .18s ease;
}}
[data-testid="stSidebarNavLink"]:hover {{
    background: rgba(255,255,255,.07); border-color: rgba(255,255,255,.10);
    transform: translateX(2px);
}}
[data-testid="stSidebarNavLink"] span, [data-testid="stSidebarNavLink"] p {{
    color: rgba(255,255,255,.80); font-weight: 500; font-size: .9rem;
}}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
    background: rgba(28,130,255,.22); border-color: rgba(28,130,255,.45);
    box-shadow: 0 4px 16px rgba(28,130,255,.26), inset 0 0 0 1px rgba(255,255,255,.05);
}}
[data-testid="stSidebarNavLink"][aria-current="page"] span,
[data-testid="stSidebarNavLink"][aria-current="page"] p {{ color: {WHITE}; font-weight: 600; }}

/* grouped-nav section labels */
[data-testid="stNavSectionHeader"],
[data-testid="stSidebarNav"] [class*="SectionHeader"] {{
    color: {BLUE_LIGHT} !important; text-transform: uppercase; letter-spacing: 1.3px;
    font-size: .66rem !important; font-weight: 700; padding: 14px 16px 4px 16px; margin: 0;
}}

/* glass user / login card */
.dcr-usercard {{
    margin: 6px 8px 6px 8px; padding: 12px 14px; border-radius: 14px;
    background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    display: flex; align-items: center; gap: 11px;
}}
.dcr-avatar {{
    height: 38px; width: 38px; border-radius: 50%; flex: 0 0 38px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Saira', sans-serif; font-weight: 700; font-size: .9rem; color: {WHITE};
    background: linear-gradient(135deg, {BLUE_BRIGHT}, {BLUE});
    box-shadow: 0 4px 12px rgba(28,130,255,.40);
}}
.dcr-uname {{ font-weight: 600; font-size: .9rem; color: {WHITE}; line-height: 1.15; }}
.dcr-urole {{ font-size: .72rem; color: #9fc6ff; margin-top: 1px; }}

/* sidebar buttons -> glass */
[data-testid="stSidebar"] .stButton button {{
    width: 100%; border-radius: 10px; font-weight: 600; font-size: .85rem;
    background: rgba(255,255,255,.08); color: {WHITE};
    border: 1px solid rgba(255,255,255,.16); transition: all .18s ease;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    background: rgba(28,130,255,.30); border-color: rgba(28,130,255,.55);
    box-shadow: 0 4px 16px rgba(28,130,255,.30); color: {WHITE};
}}

/* sidebar footer + dividers + scrollbar */
.dcr-side-foot {{
    margin: 12px 14px 4px 14px; font-size: .68rem;
    color: rgba(255,255,255,.42); letter-spacing: .3px;
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.10); margin: 8px 0; }}
[data-testid="stSidebar"] ::-webkit-scrollbar {{ width: 7px; }}
[data-testid="stSidebar"] ::-webkit-scrollbar-thumb {{
    background: rgba(255,255,255,.16); border-radius: 4px;
}}

/* misc */
hr {{ border-color: #e6edf6; }}
[data-testid="stDataFrame"] {{ border: 1px solid #e6edf6; border-radius: 10px; overflow: hidden; }}
a {{ color: {BLUE}; }}
</style>
"""


def apply_brand() -> None:
    """Inject brand fonts + CSS. Call once per page after set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    """Render the navy brand banner with the white DCR logo."""
    logo = _logo_b64()
    img = f'<img class="dcr-logo" src="data:image/png;base64,{logo}"/>' if logo else ""
    sub = f'<div class="dcr-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="dcr-header">{img}'
        f'<div><p class="dcr-title">{title}</p>{sub}</div></div>',
        unsafe_allow_html=True,
    )


def _initials(name: str) -> str:
    parts = [p for p in name.replace("@", " ").replace(".", " ").split() if p]
    if not parts:
        return "DC"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


@st.dialog("Sign in")
def _login_dialog() -> None:
    """Placeholder auth modal — does not validate or store credentials."""
    st.write("Access your Dana Capital Realty workspace.")
    email = st.text_input("Email", placeholder="you@danacapitalrealty.com")
    st.text_input("Password", type="password", placeholder="••••••••")
    col1, col2 = st.columns(2)
    if col1.button("Sign in", type="primary", width="stretch"):
        name = email.split("@")[0].replace(".", " ").title() if email else "Guest User"
        st.session_state["dcr_user"] = {
            "name": name or "Guest User", "email": email, "role": "Administrator",
        }
        st.rerun()
    col2.button("Continue with Google", width="stretch", disabled=True)
    st.caption("Demo placeholder — credentials are not validated or stored.")


def render_sidebar() -> None:
    """Render the glass user/login card + footer at the foot of the sidebar.

    Call once in the entry script (app.py) after st.navigation, before nav.run().
    """
    user = st.session_state.get("dcr_user")
    with st.sidebar:
        st.markdown("<hr/>", unsafe_allow_html=True)
        if user:
            st.markdown(
                f'<div class="dcr-usercard"><div class="dcr-avatar">{_initials(user["name"])}</div>'
                f'<div><div class="dcr-uname">{user["name"]}</div>'
                f'<div class="dcr-urole">{user.get("role", "Member")}</div></div></div>',
                unsafe_allow_html=True,
            )
            if st.button("Sign out", key="dcr_signout"):
                st.session_state.pop("dcr_user", None)
                st.rerun()
        else:
            st.markdown(
                '<div class="dcr-usercard"><div class="dcr-avatar">DC</div>'
                '<div><div class="dcr-uname">Guest</div>'
                '<div class="dcr-urole">Not signed in</div></div></div>',
                unsafe_allow_html=True,
            )
            if st.button("Sign in", key="dcr_signin", type="primary"):
                _login_dialog()
        st.markdown(
            '<div class="dcr-side-foot">Dana Capital Realty &middot; FUB Warehouse</div>',
            unsafe_allow_html=True,
        )


def style_fig(fig):
    """Apply the brand look to a plotly figure (fonts, palette, clean axes)."""
    fig.update_layout(
        font_family="Montserrat, sans-serif",
        title_font_family="Saira, sans-serif",
        colorway=PLOTLY_COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, l=12, r=12, b=12),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#e6edf6", zeroline=False)
    return fig
