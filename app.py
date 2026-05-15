import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- LOGIQUE DE RÉCUPÉRATION DES FLOORS PAR SEGMENT ---
def get_segmented_floors(player_slug, is_in_season, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # En 2026, on filtre par date de saison ou tag spécifique
    # Pour l'exemple, on considère que In-Season = Saison 2025-2026
    # On adapte la requête pour demander les floors du même segment que l'annonce
    season_filter = '["2025-2026"]' if is_in_season else '[]' # Filtre simplifié
    
    query = """
    query GetSegmentedFloors($slug: String!) {
      tokens {
        limited: liveSingleSaleOffers(playerSlug: $slug, rarities: [limited], first: 10) {
          nodes { 
            senderSide { anyCards { season { name } } }
            receiverSide { amounts { eurCents } } 
          }
        }
        rare: liveSingleSaleOffers(playerSlug: $slug, rarities: [rare], first: 10) {
          nodes { 
            senderSide { anyCards { season { name } } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        data = res.get('data', {}).get('tokens', {})
        current_s = "2025-2026"

        def find_min(nodes, in_season_req):
            prices = []
            for n in nodes:
                s_name = n['senderSide']['anyCards'][0]['season']['name']
                match = (current_s in s_name) if in_season_req else (current_s not in s_name)
                if match and n.get('receiverSide', {}).get('amounts', {}).get('eurCents'):
                    prices.append(float(n['receiverSide']['amounts']['eurCents'])/100)
            return min(prices) if prices else None

        f_lim = find_min(data.get('limited', {}).get('nodes', []), is_in_season)
        f_rare = find_min(data.get('rare', {}).get('nodes', []), is_in_season)
        
        return f_lim, f_rare
    except:
        return None, None

def scan_arbitrage_segmented(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    since_date = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    
    query = """
    query GetFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 30, sport: FOOTBALL, updatedAfter: $since) {
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
        current_season = "2025-2026"
        
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                s_name = card.get('season', {}).get('name', "")
                is_in_season = current_season in s_name
                
                player_slug = card.get('anyPlayer', {}).get('slug')
                price_listing = float(eur_cents) / 100
                
                # On récupère les floors DU MÊME TYPE (In ou Classic)
                f_lim, f_rare = get_segmented_floors(player_slug, is_in_season, jwt_token)
                
                ratio = round(price_listing / f_lim, 2) if f_lim else None
                
                findings.append({
                    "Vente": datetime.fromisoformat(n.get('startDate').replace('Z', '+00:00')).strftime("%H:%M"),
                    "Joueur": card.get('anyPlayer', {}).get('displayName'),
                    "Saison": "In-Season" if is_in_season else "Classic",
                    "Prix Annonce (€)": price_listing,
                    "Floor Rare Segment (€)": f_rare,
                    "Floor Lim Segment (€)": f_lim,
                    "Ratio": ratio,
                    "Slug": player_slug
                })
        return findings
    except:
        return []

# --- UI ---
st.set_page_config(page_title="Arbitrage Segmente", layout="wide")
st.title("🎯 Arbitrage Cible : In-Season vs Classic")

if st.session_state.get('token'):
    if st.button("🔄 Rafraîchir le Scan"): st.rerun()

    results = scan_arbitrage_segmented(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        
        def apply_styles(row):
            styles = [''] * len(row)
            # Alerte si prix annoncé < floor rare actuel de son segment
            if row['Floor Rare Segment (€)'] and row['Prix Annonce (€)'] < row['Floor Rare Segment (€)']:
                styles[3] = 'background-color: #fff3cd; color: #856404; font-weight: bold'
            # Alerte ratio
            if row['Ratio'] and float(row['Ratio']) < 4.0:
                styles[6] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            return styles

        st.dataframe(df.style.apply(apply_styles, axis=1), use_container_width=True)
    else:
        st.info("Scan en cours...")
