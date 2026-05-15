import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- RÉCUPÉRATION DES FLOORS (LIM & RARE) ---
def get_floors(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFloors($slug: String!) {
      tokens {
        limited: liveSingleSaleOffers(playerSlug: $slug, rarities: [limited], first: 1) {
          nodes { receiverSide { amounts { eurCents } } }
        }
        rare: liveSingleSaleOffers(playerSlug: $slug, rarities: [rare], first: 5) {
          nodes { receiverSide { amounts { eurCents } } }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        data = res.get('data', {}).get('tokens', {})
        
        # Floor Limited
        lim_nodes = data.get('limited', {}).get('nodes', [])
        f_lim = float(lim_nodes[0]['receiverSide']['amounts']['eurCents'])/100 if lim_nodes else None
        
        # Floor Rare (le moins cher de la liste)
        rare_nodes = data.get('rare', {}).get('nodes', [])
        rare_prices = [float(n['receiverSide']['amounts']['eurCents'])/100 for n in rare_nodes if n.get('receiverSide', {}).get('amounts')]
        f_rare = min(rare_prices) if rare_prices else None
        
        return f_lim, f_rare
    except: return None, None

def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    since_date = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    
    # Requête incluant la saison pour distinguer In-Season / Classic
    query = """
    query GetLiveFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 40, sport: FOOTBALL, updatedAfter: $since) {
          nodes {
            senderSide { 
              anyCards { 
                rarityTyped 
                season { name }
                anyPlayer { displayName slug } 
              } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'since': since_date}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        
        current_season = "2025-2026" # À ajuster selon la saison actuelle Sorare
        
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                season_name = card.get('season', {}).get('name', "")
                status = "🟢 In-Season" if current_season in season_name else "⚪ Classic"
                
                player_name = card.get('anyPlayer', {}).get('displayName')
                player_slug = card.get('anyPlayer', {}).get('slug')
                price_rare_listing = float(eur_cents) / 100
                
                # Récupération des floors pour comparaison
                f_lim, f_rare_market = get_floors(player_slug, jwt_token)
                
                ratio = round(price_rare_listing / f_lim, 2) if f_lim else None
                
                findings.append({
                    "Vente": datetime.fromisoformat(n.get('startDate').replace('Z', '+00:00')).strftime("%H:%M"),
                    "Joueur": player_name,
                    "Type": status,
                    "Prix Annonce (€)": price_rare_listing,
                    "Floor Rare (€)": f_rare_market,
                    "Floor Lim (€)": f_lim,
                    "Ratio (R/L)": ratio,
                    "Slug": player_slug
                })
        return findings
    except Exception as e:
        return []

# --- UI STREAMLIT ---
st.set_page_config(page_title="Scanner Arbitrage Pro", layout="wide")
st.title("🚀 Arbitrage : In-Season vs Classic")

# ... (Bloc de connexion inchangé) ...

if st.session_state.get('token'):
    if st.button("🔄 Rafraîchir le flux"): st.rerun()

    results = scan_arbitrage_live(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        
        def highlight_logic(row):
            styles = [''] * len(row)
            try:
                # Si le prix de l'annonce est inférieur au floor rare du marché = Affaire !
                if row['Prix Annonce (€)'] < row['Floor Rare (€)']:
                    styles[3] = 'background-color: #fff3cd; color: #856404;' # Jaune : Prix plus bas que le floor
                
                # Si le ratio Rare/Limited est top
                if row['Ratio (R/L)'] is not None and float(row['Ratio (R/L)']) < 4.0:
                    styles[6] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return styles

        st.dataframe(df.style.apply(highlight_logic, axis=1), use_container_width=True)
    else:
        st.info("Recherche de nouvelles opportunités Rares...")
