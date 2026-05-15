import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

def get_segmented_floors(player_slug, is_in_season, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 40) {
          nodes { 
            senderSide { anyCards { rarityTyped seasonYear } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        lim_prices, rare_prices = [], []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            card_is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
            if card_is_in_season == is_in_season:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_prices.append(p)
                    if card['rarityTyped'] == 'rare': rare_prices.append(p)
        return (min(lim_prices) if lim_prices else None), (min(rare_prices) if rare_prices else None)
    except: return None, None

def scan_arbitrage_final(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 80, sport: FOOTBALL) {
          nodes {
            senderSide { 
              anyCards { rarityTyped seasonYear anyPlayer { displayName slug } } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in_season, jwt_token)
                price_now = float(eur_cents) / 100
                findings.append({
                    "Vente": n.get('startDate'),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Catégorie": "🟢 In-Season" if is_in_season else "⚪ Classic",
                    "Prix (€)": round(price_now, 2),
                    "Floor Rare (€)": round(f_rare, 2) if f_rare else None,
                    "Floor Lim (€)": round(f_lim, 2) if f_lim else None,
                    "Ratio": round(price_now / f_lim, 2) if f_lim else None,
                    "Slug": card['anyPlayer']['slug']
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- UI ---
st.set_page_config(page_title="Scanner Arbitrage PRO", layout="wide")
st.title("🎯 Arbitrage : In-Season vs Classic")

if st.session_state.get('token'):
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🚀 Lancer le Scan"): st.rerun()
    
    data = scan_arbitrage_final(st.session_state['token'])
    if data:
        df = pd.DataFrame(data).drop(columns=['Slug'])
        
        def style_df(row):
            styles = [''] * len(row)
            if row['Ratio'] and float(row['Ratio']) < 4.0:
                styles[6] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            if row['Floor Rare (€)'] and row['Prix (€)'] < row['Floor Rare (€)']:
                styles[3] = 'background-color: #fff3cd; color: #856404;'
            return styles

        st.dataframe(df.style.apply(style_df, axis=1), use_container_width=True)
    else:
        st.info("Prêt pour le scan.")
