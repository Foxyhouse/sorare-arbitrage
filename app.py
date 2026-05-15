import streamlit as st
import requests
import pandas as pd

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

def get_segmented_floors(player_slug, is_in_season, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 50) {
          nodes { 
            senderSide { anyCards { rarityTyped seasonYear } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
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
        
        return min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None
    except:
        return None, None

def scan_arbitrage_final(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # Augmentation du scan à 150 pour trouver plus de Rares
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 150, sport: FOOTBALL) {
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
                label = "🟢 In-Season" if is_in_season else "⚪ Classic"
                
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in_season, jwt_token)
                
                price_now = float(eur_cents) / 100
                
                # --- FILTRE : Uniquement si prix <= Floor Rare ---
                if f_rare is not None and price_now <= f_rare:
                    ratio = round(price_now / f_lim, 2) if f_lim else None
                    
                    findings.append({
                        "Vente": n.get('startDate'),
                        "Joueur": card['anyPlayer']['displayName'],
                        "Catégorie": label,
                        "Prix (€)": round(price_now, 2),
                        "Floor Rare (€)": round(f_rare, 2),
                        "Floor Lim (€)": round(f_lim, 2) if f_lim else None,
                        "Ratio": ratio,
                        "Slug": card['anyPlayer']['slug']
                    })
        
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except Exception as e:
        st.error(f"Erreur : {e}")
        return []

# --- UI ---
st.title("🎯 Sniper Arbitrage : Undercuts uniquement")

if st.session_state.get('token'):
    if st.button("🚀 Lancer le Scan Profond"):
        data = scan_arbitrage_final(st.session_state['token'])
        if data:
            df = pd.DataFrame(data).drop(columns=['Slug'])
            
            def style_df(row):
                styles = [''] * len(row)
                # Vert si ratio intéressant
                if row['Ratio'] and float(row['Ratio']) < 4.0:
                    styles[6] = 'background-color: #d4edda; color: #155724; font-weight: bold'
                # Jaune/Orange si c'est un undercut parfait (Prix <= Floor)
                if row['Prix (€)'] <= row['Floor Rare (€)']:
                    styles[3] = 'background-color: #fff3cd; color: #856404; border: 1px solid orange;'
                return styles

            st.dataframe(df.style.apply(style_df, axis=1), use_container_width=True)
        else:
            st.warning("Aucune opportunité (Prix au floor) détectée sur les 150 dernières offres.")
