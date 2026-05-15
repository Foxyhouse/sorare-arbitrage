import streamlit as st
import requests
import bcrypt
import pandas as pd

# --- CONFIGURATION ---
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

def scan_audit_100(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # ÉTAPE 1 : ON FORCE LE FILTRE SUR LES RARES UNIQUEMENT
    query = """
    query Get100Rares {
      tokens {
        liveSingleSaleOffers(first: 100, rarities: [rare], sport: FOOTBALL) {
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
        st.session_state['audit_raw'] = res_json # Debug
        
        if "errors" in res_json:
            st.error(f"Erreur API : {res_json['errors'][0]['message']}")
            return []

        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        findings = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards:
                c = cards[0]
                findings.append({
                    "Date": n.get('startDate'),
                    "name": c.get('anyPlayer', {}).get('displayName'),
                    "slug": c.get('anyPlayer', {}).get('slug'),
                    "rarity_check": c.get('rarityTyped'), # Pour vérifier la casse
                    "rare_price": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        
        # ÉTAPE 2 : CALCUL DES RATIOS
        for item in findings[:15]: # On limite le calcul intensif aux 15 premières
            item['lim_price'] = get_limited_floor(item['slug'], jwt_token)
            if item['lim_price']:
                item['Ratio'] = round(item['rare_price'] / item['lim_price'], 2)
            else:
                item['Ratio'] = "N/A"
                
        return findings
    except Exception as e:
        st.error(f"Crash : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Audit Arbitrage 100", layout="wide")
st.title("🔎 Audit Tactique : Flux 100 Rares")

if 'token' not in st.session_state:
    st.warning("Connecte-toi d'abord.")
else:
    if st.button("🚀 Lancer l'Audit des 100 Rares"):
        with st.spinner("Interrogation du marché live..."):
            data = scan_audit_100(st.session_state['token'])
            if data:
                st.success(f"Trouvé {len(data)} offres Rares récentes.")
                st.dataframe(pd.DataFrame(data), use_container_width=True)
            else:
                st.error("La liste est vide. Regarde le JSON Brut ci-dessous.")

    st.divider()
    if st.checkbox("⚙️ VOIR LE JSON BRUT (LA SOURCE DE VÉRITÉ)"):
        if 'audit_raw' in st.session_state:
            st.json(st.session_state['audit_raw'])
        else:
            st.info("Aucune donnée à afficher. Lance un audit.")
