import sys
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TIMEOUT = 20
_ssl_fallback_warned = False


def http_request(method, url, **kwargs):
    """GET/POST z timeoutem. Przy lokalnym problemie CA (antywirus/proxy) ponawia bez weryfikacji SSL."""
    global _ssl_fallback_warned
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        if not _ssl_fallback_warned:
            print("⚠️ Lokalny problem z certyfikatem SSL – ponawiam żądania bez weryfikacji.")
            _ssl_fallback_warned = True
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        kwargs["verify"] = False
        return requests.request(method, url, **kwargs)

# Strony do monitorowania
STORES = {
    'diabetyk24': {
        'url': "https://diabetyk24.pl/sensor-cgm-simpleratm-sync-1-szt-do-pompy-minimed-780g-mmt-5120d2/availability_notification",
        'unavailable_text': "brak produktu na stanie",
        'name': "Diabetyk24",
        'check_type': 'text'
    },
    'medital': {
        'url': "https://medital.pl/pl/p/Sensor-CGM-Simplera-Sync-Medtronic-do-pompy-780G-MMT-5120/706",
        'unavailable_text': "niedostęp",
        'available_text': "dostępny",
        'name': "Medital",
        'check_type': 'css',
        'selector': 'div.row.availability span.second'
    },
    'infusion': {
        'url': "https://infusion.pl/sensory-i-transmitery-/753-1414-sensor-simplera-sync-do-pompy-780g.html#/223-simplera-r0301_ponizej_26_lat",
        'unavailable_text': "Oczekiwanie na dostawę",
        'name': "Infusion",
        'check_type': 'id',
        'element_id': 'product-availability',
        'element_type': 'span'
    },
    'sosdiabetyka': {
        'url': "https://www.sosdiabetyka.pl/produkt/sensor-cgm-simplera-sync-mmt-5120",
        'unavailable_text': "niedostęp",
        'available_text': "dostępny",
        'name': "SOS Diabetyka",
        'check_type': 'css',
        'selector': 'div.products-right p'
    }
}

NTFY_URL = "https://ntfy.sh/sensor-cgm"

def element_is_available(element, store_config):
    text = element.get_text().lower().strip()
    unavailable = store_config.get('unavailable_text', '').lower()
    available = store_config.get('available_text', '').lower()
    if unavailable and unavailable in text:
        return False
    if available:
        return available in text
    return True


def check_availability_by_element(soup, store_config):
    if store_config['check_type'] == 'css':
        elements = soup.select(store_config['selector'])
        if not elements:
            print(f"⚠️ Nie znaleziono elementu dostępności w {store_config['name']}")
            return False
        for element in elements:
            if element_is_available(element, store_config):
                return True
        return False

    # Sprawdzanie dostępność produktu wyszukując element po klasie, id lub tagu
    if store_config['check_type'] == 'button':
        if 'button_class' in store_config: 
            element = soup.find('button', class_=store_config['button_class'])
        else:
            element = soup.find('button', string=lambda text: text and store_config['unavailable_text'] in text)
    elif 'class_name' in store_config:
        element = soup.find(store_config['element_type'], class_=store_config['class_name'])
    elif 'element_id' in store_config:
        element = soup.find(store_config['element_type'], id=store_config['element_id'])
    else:
        return False

    if not element:
        if store_config['check_type'] == 'id':
            return False
        print(f"⚠️ Nie znaleziono elementu dostępności w {store_config['name']}")
        return False
    
    # Sprawdzanie tekstu buttona
    if store_config['check_type'] == 'button':
        if 'button_class' in store_config:
            return False
        return False 
    elif store_config['check_type'] == 'id':
        if store_config['name'] == 'Infusion':
            availability_text = element.get_text().lower().strip()
            return 'oczekiwanie na dostawę' not in availability_text
        return True
    elif store_config['check_type'] == 'class':
        availability_text = element.get_text().lower().strip()
        return store_config['unavailable_text'].lower() not in availability_text
    
    availability_text = element.get_text().lower().strip()
    return store_config['unavailable_text'].lower() not in availability_text

def check_product(store_config):
    try:
        response = http_request("GET", store_config['url'])
        if store_config['name'] == 'Diabetyk24' and response.status_code == 404:
            print(f"✅ Strona niedostępna w {store_config['name']} – wysyłanie powiadomienia.")
            send_notification(store_config['name'])
            return True
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        is_available = False
        if store_config['check_type'] in ['class', 'id', 'button', 'css']:
            is_available = check_availability_by_element(soup, store_config)
        else:
            # Sprawdzanie dla diabetyk24 w tekscie
            text = soup.get_text().lower()
            is_available = store_config['unavailable_text'].lower() not in text

        if is_available:
            print(f"✅ Produkt dostępny w {store_config['name']} – wysyłanie powiadomienia.")
            send_notification(store_config['name'])
            return True
        else:
            print(f"❌ Produkt niedostępny w {store_config['name']}.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Błąd połączenia z {store_config['name']}: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd w {store_config['name']}: {str(e)}")
        return False

# Wysyłanie powiadomienia   
def send_notification(store_name):
    message = f'🎉 Sensor CGM jest DOSTĘPNY w sklepie {store_name}!'
    headers = {'Content-Type': 'text/plain; charset=utf-8'}
    http_request("POST", NTFY_URL, data=message.encode('utf-8'), headers=headers)

def check_all_stores():
    for store_id, store_config in STORES.items():
        check_product(store_config)

if __name__ == "__main__":
    check_all_stores()
