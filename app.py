import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

# --- LOGIQUE DE RÉCUPÉRATION DES FLOORS ---
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

def scan_arbitrage_flux_libre(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # On scanne les 100 dernières offres FOOTBALL
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL) {
          nodes {
            senderSide { 
              anyCards { slug rarityTyped seasonYear anyPlayer { displayName slug } } 
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
                price_now = round(float(eur_cents) / 100, 2)
                
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in_season, jwt_token)
                ratio = round(price_now / f_lim, 2) if f_lim else None
                
                findings.append({
                    "Lien": f"https://sorare.com/football/cards/{card['slug']}",
                    "Vente": n.get('startDate'),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Catégorie": "🟢 In-Season" if is_in_season else "⚪ Classic",
                    "Prix (€)": price_now,
                    "Floor Rare (€)": round(f_rare, 2) if f_rare else None,
                    "Floor Lim (€)": round(f_lim, 2) if f_lim else None,
                    "Ratio": ratio
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- UI ---
st.set_page_config(page_title="Sniper Arbitrage", layout="wide")
st.title("🎯 Arbitrage Live (Auto-Refresh 60s)")

# Affichage de l'heure pour confirmer le refresh
st.sidebar.markdown(f"🕒 **Dernière mise à jour :**\n{datetime.now().strftime('%H:%M:%S')}")

if st.session_state.get('token'):
    # Exécution du scan
    data = scan_arbitrage_flux_libre(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data)
        
        def style_df(row):
            styles = [''] * len(row)
            # Vert si ratio < 4
            if row['Ratio'] and float(row['Ratio']) < 4.0:
                styles[7] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            # Jaune si undercut (Prix <= Floor Rare)
            if row['Floor Rare (€)'] and row['Prix (€)'] <= row['Floor Rare (€)']:
                styles[4] = 'background-color: #fff3cd; color: #856404;'
            return styles

        st.dataframe(
            df.style.apply(style_df, axis=1),
            column_config={
                "Lien": st.column_config.LinkColumn("🛒", display_text="Acheter"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Recherche de Rares...")

    # Logique d'Auto-Refresh : attend 60s puis relance
    time.sleep(60)
    st.rerun()
else:
    st.warning("Veuillez vous connecter pour lancer le scanner.")
