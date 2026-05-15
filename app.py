import streamlit as st
import requests
import bcrypt
import pandas as pd

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, rarities: [limited], first: 1) {
          nodes { receiverSide { amounts { eurCents } } }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        if nodes:
            return float(nodes[0]['receiverSide']['amounts']['eurCents']) / 100
    except: pass
    return None

def scan_arbitrage_live_massive(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On passe à 500 pour ratisser très large et coller au site
    query = """
    query GetLiveFluxMassive {
      tokens {
        liveSingleSaleOffers(first: 500, sport: FOOTBALL) {
          nodes {
            senderSide {
              anyCards {
                rarityTyped
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
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        rare_findings = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            card = cards[0]
            # SÉCURITÉ : On vérifie la rareté sans se soucier de la casse (RARE ou rare)
            current_rarity = str(card.get('rarityTyped', '')).lower()
            
            if current_rarity == 'rare':
                rare_findings.append({
                    "Date": n.get('startDate'),
                    "name": card.get('anyPlayer', {}).get('displayName'),
                    "slug": card.get('anyPlayer', {}).get('slug'),
                    "rare_price": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        
        if not rare_findings: return []

        # On traite les 25 premières Rares trouvées pour ne pas surcharger
        rare_findings = rare_findings[:25]
        alias_query = "query GetFloors { "
        for i, item in enumerate(rare_findings):
            alias_query += f'f{i}: tokens {{ liveSingleSaleOffers(playerSlug: "{item["slug"]}", rarities: [limited], first: 1) {{ nodes {{ receiverSide {{ amounts {{ eurCents }} }} }} }} }} '
        alias_query += " }"
        
        res_floors = requests.post(API_URL, json={'query': alias_query}, headers=headers).json()
        floors_data = res_floors.get('data', {})

        final_data = []
        for i, item in enumerate(rare_findings):
            nodes_lim = floors_data.get(f'f{i}', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
            lim_floor = float(nodes_lim[0]['receiverSide']['amounts']['eurCents']) / 100 if nodes_lim else None
            ratio = item['rare_price'] / lim_floor if lim_floor else None
            
            final_data.append({
                "Mise en ligne": item['Date'],
                "Joueur": item['name'],
                "Prix Rare (€)": item['rare_price'],
                "Floor Limited (€)": lim_floor,
                "Ratio": round(ratio, 2) if ratio else "N/A"
            })
        return final_data
    except: return []

# --- UI ---
st.set_page_config(page_title="Arbitrage Scanner Massive", layout="wide")
st.title("🚀 Scanner Temps Réel (Force 500)")

if 'token' not in st.session_state: 
    # Ton bloc de login ici...
    pass 

# Affichage direct pour ton test
if st.button("🔄 Lancer le Scan Profond"):
    with st.spinner("Analyse des 500 derniers mouvements de marché..."):
        data = scan_arbitrage_live_massive(st.session_state['token'])
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.error("Toujours rien. Vérifie ton jeton JWT ou filtre sur une autre rareté pour tester.")
