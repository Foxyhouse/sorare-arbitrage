import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- RÉCUPÉRATION FLOORS ---
def get_segmented_floors(player_slug, season_name, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 30) {
          nodes { 
            senderSide { anyCards { rarityTyped season { name } } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        
        lim_prices = []
        rare_prices = []
        
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            # On ne compare qu'avec la MÊME saison
            if card['season']['name'] == season_name:
                price = float(n['receiverSide']['amounts']['eurCents']) / 100
                if card['rarityTyped'] == 'limited': lim_prices.append(price)
                if card['rarityTyped'] == 'rare': rare_prices.append(price)
        
        return min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None
    except:
        return None, None

def scan_arbitrage_v3(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    since = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    
    query = """
    query GetFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 40, sport: FOOTBALL, updatedAfter: $since) {
          nodes {
            senderSide { 
              anyCards { rarityTyped season { name } anyPlayer { displayName slug } } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'since': since}}, headers=headers, timeout=15).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        if not nodes:
            return [], "Aucune offre trouvée dans le flux 24h."

        current_season = "2025-2026" # On garde ce repère mais on affiche le nom réel
        findings = []
        
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                s_name = card.get('season', {}).get('name', "Inconnue")
                
                # Récupération des floors pour CETTE saison spécifique
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], s_name, jwt_token)
                
                price_now = float(eur_cents) / 100
                ratio = round(price_now / f_lim, 2) if f_lim else None
                
                findings.append({
                    "Vente": datetime.fromisoformat(n.get('startDate').replace('Z', '+00:00')).strftime("%H:%M"),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Saison": s_name,
                    "Type": "🟢 In-Season" if current_season in s_name else "⚪ Classic",
                    "Prix (€)": price_now,
                    "Floor Rare (€)": f_rare,
                    "Floor Lim (€)": f_lim,
                    "Ratio": ratio,
                    "Slug": card['anyPlayer']['slug']
                })
        return findings, None
    except Exception as e:
        return [], f"Erreur : {str(e)}"

# --- INTERFACE ---
st.set_page_config(page_title="Arbitrage V3", layout="wide")
st.title("🎯 Arbitrage Cible : In-Season vs Classic")

if st.session_state.get('token'):
    if st.sidebar.button("🔄 Rafraîchir"): st.rerun()

    # Utilisation d'un container pour éviter le blocage visuel
    with st.spinner("Analyse du flux..."):
        results, err = scan_arbitrage_v3(st.session_state['token'])
    
    if err:
        st.error(err)
    elif results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        
        def style_row(row):
            styles = [''] * len(row)
            # Vert si ratio < 4
            if row['Ratio'] and float(row['Ratio']) < 4.0:
                styles[7] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            # Jaune si l'annonce est MOINS CHÈRE que le floor rare connu
            if row['Floor Rare (€)'] and row['Prix (€)'] < row['Floor Rare (€)']:
                styles[4] = 'background-color: #fff3cd; color: #856404;'
            return styles

        st.dataframe(df.style.apply(style_row, axis=1), use_container_width=True)
    else:
        st.warning("Aucune carte Rare trouvée dans les dernières annonces. Réessaie.")
