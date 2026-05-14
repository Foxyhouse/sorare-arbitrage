import streamlit as st

st.set_page_config(page_title="Sorare Arbitrage 2026", layout="wide")

st.title("⚽ Sorare Arbitrage : Limited vs Rare (Ligue 1)")
st.write("Compare la rentabilité réelle des paliers Hot Streak.")

# --- DONNÉES OFFICIELLES 2026 ---
REWARD_RATIO = 3.0  # $20 vs $5
BONUS_RARE = 1.10   # +10% de bonus de rareté

# --- CALCULS ---
def get_analysis(name, p_lim, p_rare, score_l15):
    ratio_prix = p_rare / p_lim
    
    # Score brut nécessaire pour P1 (360 Lim / 400 Rare)
    brut_necessaire_lim = 360 / 1.05 # Saison +5%
    brut_necessaire_rare = 400 / (1.05 + 0.10) # Saison + Rareté
    
    st.subheader(f"📊 Analyse pour {name}")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Ratio de Prix", f"x{ratio_prix:.2f}")
        if ratio_prix < REWARD_RATIO:
            st.success("✅ Ratio Rentable (< 4)")
        else:
            st.error("❌ Rare trop chère")

    with col2:
        diff_difficulte = (brut_necessaire_rare / brut_necessaire_lim - 1) * 100
        st.metric("Surcoût Sportif", f"+{diff_difficulte:.1f}%")
        st.write("Points bruts pour P1")

    with col3:
        roi_efficiency = REWARD_RATIO / ratio_prix
        st.metric("Efficience du Cash", f"x{roi_efficiency:.2f}")
        st.write("Gain potentiel vs Limited")

# --- INTERFACE ---
st.divider()
st.sidebar.header("Paramètres Joueurs")

# Hervé Koffi
st.sidebar.subheader("Hervé Koffi")
k_lim = st.sidebar.number_input("Prix Limited (Koffi)", value=5.70)
k_rare = st.sidebar.number_input("Prix Rare (Koffi)", value=15.90)

# Jordan Lefort
st.sidebar.subheader("Jordan Lefort")
l_lim = st.sidebar.number_input("Prix Limited (Lefort)", value=0.60)
l_rare = st.sidebar.number_input("Prix Rare (Lefort)", value=1.20)

get_analysis("Hervé Koffi", k_lim, k_rare, 59)
st.divider()
get_analysis("Jordan Lefort", l_lim, l_rare, 51)
