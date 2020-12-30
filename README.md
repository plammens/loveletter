# LoveLetter


This project exposes the following top-level Python packages:

- **`loveletter`** – 
  The core package with all the game logic and nothing else.
- **`loveletter_multiplayer`** –
  A sample multiplayer engine based on a client/server model for playing games over a
  network using TCP sockets.
  It uses `asyncio` and `async`/`await` as its "concurrency framework", so to speak.
  Depends on `loveletter`.

The reason these are split into several top-level packages instead of having all be part
of a single `loveletter` package is to make it more modular and easier to replace any 
of the components:
for example, one could implement a different user interface for local-only games, and
they would only need the core `loveletter` package; 
or one could implement a different multiplayer engine;
etc.
