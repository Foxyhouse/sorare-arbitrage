import streamlit as st
import requests
import bcrypt
import pandas as pd

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # Ici, playerSlug est accepté, donc on peut filtrer la rareté pour le floor
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 10) {
          nodes {
            senderSide { anyCards { rarityTyped } }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        lim_prices = []
        for n in nodes:
            card = n.get('senderSide', {}).get('anyCards', [{}])[0]
            if card.get('rarityTyped') == 'limited':
                price = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if price: lim_prices.append(float(price) / 100)
        return min(lim_prices) if lim_prices else None
    except: return None

def scan_arbitrage_final(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # REQUÊTE SANS ARGUMENT 'rarities' (Validé par l'erreur JSON)
    query = """
    query GetFlux {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL) {
          nodes {
            senderSide {
              anyCards {
                slug
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
        response = requests.post(API_URL, json={'query': query}, headers=headers)
        res_json = response.json()
        st.session_state['audit_raw'] = res_json
        
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        findings = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            c = cards[0]
            # Tri manuel en Python
            if c.get('rarityTyped') == 'rare':
                findings.append({
                    "Date": n.get('startDate'),
                    "Joueur": c.get('anyPlayer', {}).get('displayName'),
                    "Slug": c.get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        
        # Calcul des ratios pour les Rares trouvées
        for item in findings[:15]: 
            item['Floor Limited (€)'] = get_limited_floor(item['Slug'], jwt_token)
            if item['Floor Limited (€)']:
                item['Ratio'] = round(item['Prix Rare (€)'] / item['Floor Limited (€)'], 2)
            else:
                item['Ratio'] = "N/A"
                
        return findings
    except Exception as e:
        st.error(f"Erreur : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Arbitrage Scanner 2026", layout="wide")
st.title("🚀 Scanner d'Arbitrage (Flux 100)")

if 'token' not in st.session_state:
    st.info("Connecte-toi via l'onglet précédent.")
else:
    if st.button("🔄 Scanner le Marché"):
        with st.spinner("Analyse du flux live..."):
            data = scan_arbitrage_final(st.session_state['token'])
            if data:
                df = pd.DataFrame(data).drop(columns=['Slug'])
                st.success(f"Trouvé {len(data)} cartes Rares dans le flux.")
                
                def highlight_ratio(s):
                    if isinstance(s, float) and s < 4.0:
                        return 'background-color: #d4edda; color: #155724; font-weight: bold'
                    return ''
                
                st.dataframe(df.style.applymap(highlight_ratio, subset=['Ratio']), use_container_width=True)
            else:
                st.warning("Aucune Rare détectée dans les 100 dernières offres. Réessaie dans 10 secondes.")

    if st.checkbox("⚙️ Debug JSON"):
        st.json(st.session_state.get('audit_raw', {}))
