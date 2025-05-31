from flask import Flask, render_template, redirect, url_for, session, jsonify
import vlc
import time
import requests

app = Flask(__name__)
# MUITO IMPORTANTE: Defina uma chave secreta forte e única!
app.secret_key = 'MUDAR_PARA_UMA_CHAVE_SECRETA_REAL_E_SEGURA'

radios = {
    "Death.FM LoFi": {
        "stream_url": "http://lo4.death.fm",
        "metadata_url": "http://death.fm/soap/FM24sevenJSON.php?action=GetCurrentlyPlaying",
        "metadata_type": "external_api"
    },
    "Rádio Exemplo (VLC Meta)": {
        "stream_url": "http://radionova.fiks.ips.pt:8000/radionova.mp3",
        "metadata_url": None,
        "metadata_type": "vlc"
    },
    # Adicione outras rádios aqui
}

instance = vlc.Instance()
player = instance.media_player_new()
current_media_vlc_object = None
vlc_metadata_now_playing = "Nenhum metadado VLC disponível"

def vlc_metadata_callback(event, media_obj):
    global vlc_metadata_now_playing
    if not media_obj:
        return
    meta = media_obj.get_meta(vlc.Meta.NowPlaying)
    if meta:
        print(f"Metadados VLC recebidos: {meta}")
        vlc_metadata_now_playing = meta
    else:
        title = media_obj.get_meta(vlc.Meta.Title)
        artist = media_obj.get_meta(vlc.Meta.Artist)
        if title and artist:
            vlc_metadata_now_playing = f"{artist} - {title}"
        elif title:
            vlc_metadata_now_playing = title

def _play_radio_internal(radio_name_to_play):
    global player, current_media_vlc_object, vlc_metadata_now_playing
    if radio_name_to_play not in radios:
        print(f"Erro: Rádio '{radio_name_to_play}' não encontrada.")
        return

    radio_info = radios[radio_name_to_play]
    stream_url = radio_info["stream_url"]
    metadata_url = radio_info.get("metadata_url")
    metadata_type = radio_info.get("metadata_type", "vlc")

    if player.is_playing():
        player.stop()

    if current_media_vlc_object:
        current_media_vlc_object.release()
        current_media_vlc_object = None
    vlc_metadata_now_playing = "Aguardando metadados VLC..."

    current_media_vlc_object = instance.media_new(stream_url)
    if not current_media_vlc_object:
        print(f"Erro: Não foi possível criar o objeto media para {stream_url}")
        return
    player.set_media(current_media_vlc_object)

    if metadata_type == "vlc":
        event_manager = current_media_vlc_object.event_manager()
        event_manager.event_attach(vlc.EventType.MediaMetaChanged,
                                   lambda event, media_obj=current_media_vlc_object: vlc_metadata_callback(event, media_obj),
                                   current_media_vlc_object)
        current_media_vlc_object.parse_with_options(vlc.MediaParseFlag.network, 1000)

    player.play()
    time.sleep(1.5)

    session['current_radio'] = radio_name_to_play
    session['current_radio_stream_url'] = stream_url
    session['current_radio_metadata_url'] = metadata_url
    session['current_radio_metadata_type'] = metadata_type

def _stop_radio_internal():
    global player, current_media_vlc_object, vlc_metadata_now_playing
    if player.is_playing():
        player.stop()
    if current_media_vlc_object:
        current_media_vlc_object.release()
        current_media_vlc_object = None
    session.pop('current_radio', None)
    session.pop('current_radio_stream_url', None)
    session.pop('current_radio_metadata_url', None)
    session.pop('current_radio_metadata_type', None)
    vlc_metadata_now_playing = "Nenhum metadado VLC disponível"

@app.route('/')
def index():
    current_radio_name = session.get('current_radio')
    initial_metadata_display = "Selecione uma rádio."
    # Inicializa para None, crucial para o template e lógica JS
    current_radio_metadata_type_for_js = None

    if current_radio_name:
        # Pega o tipo de metadados da sessão, se uma rádio estiver ativa
        current_radio_metadata_type_for_js = session.get('current_radio_metadata_type')
        if current_radio_metadata_type_for_js == 'external_api':
            initial_metadata_display = "Carregando metadados da API..."
        elif current_radio_metadata_type_for_js == 'vlc':
            initial_metadata_display = vlc_metadata_now_playing
        else:
            # Caso para tipos não definidos ou se 'metadata_type' não estiver na config da rádio
            initial_metadata_display = "Metadados não configurados para esta rádio."
    
    return render_template('index.html',
                           radios=radios.keys(),
                           current_radio=current_radio_name,
                           initial_metadata=initial_metadata_display,
                           # Passa o tipo de metadados para o JavaScript usar
                           current_radio_metadata_type_for_js=current_radio_metadata_type_for_js)

@app.route('/play/<radio_name>')
def play(radio_name):
    _play_radio_internal(radio_name)
    return redirect(url_for('index'))

@app.route('/stop')
def stop():
    _stop_radio_internal()
    return redirect(url_for('index'))

@app.route('/get_current_metadata_feed')
def get_current_metadata_feed_route():
    radio_name = session.get('current_radio')
    metadata_url = session.get('current_radio_metadata_url')
    metadata_type = session.get('current_radio_metadata_type')

    if not radio_name:
        return jsonify(error="Nenhuma rádio tocando", radio=None, source="none", data={})

    if metadata_type == "external_api" and metadata_url:
        try:
            response = requests.get(metadata_url, timeout=5)
            response.raise_for_status()
            api_data = response.json()
            return jsonify(
                radio=radio_name,
                source="external_api",
                data={
                    "track": api_data.get("Track"),
                    "artist": api_data.get("Artist"),
                    "album": api_data.get("Album"),
                    "cover_link": api_data.get("CoverLink"),
                    "raw": api_data
                }
            )
        except requests.exceptions.Timeout:
            print(f"Timeout ao buscar metadados da API: {metadata_url}")
            return jsonify(error="Timeout ao buscar metadados da API.", radio=radio_name, source="external_api_error", data={})
        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar metadados da API: {e}")
            return jsonify(error=f"Erro na API de metadados: {str(e)}", radio=radio_name, source="external_api_error", data={})
        except ValueError as e: # Erro ao decodificar JSON
            print(f"Erro ao decodificar JSON da API: {e}")
            return jsonify(error="Erro ao processar resposta da API (JSON inválido).", radio=radio_name, source="external_api_json_error", data={})

    elif metadata_type == "vlc":
        return jsonify(
            radio=radio_name,
            source="vlc",
            data={"now_playing_string": vlc_metadata_now_playing}
        )
    else:
        return jsonify(error="Tipo de metadados não configurado ou desconhecido para esta rádio.", radio=radio_name, source="unknown", data={})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', use_reloader=False)
    