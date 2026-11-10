/* Список игр О!ркады. Каждая игра в своём файле и регистрируется через Arcade.register. */
['chemodanchiki-lcd', 'zmeyka-naberezhnaya', 'pyatnashki-etazhi', 'gorodki-galka', 'morskoy-boy-nomera',
 'etazhi-blocks', 'pary-vidy', 'chaika-flappy', 'zvonok-na-resepshn', 'shezlongi-breakout']
  .forEach(id => { const s = document.createElement('script'); s.src = '/waitgames/games/' + id + '.js'; s.async = false; document.body.appendChild(s) });
