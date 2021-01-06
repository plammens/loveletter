# LoveLetter

![](https://github.com/plammens/loveletter/workflows/Python%20application/badge.svg)

A Python replica of the board game [Love Letter by Z-MAN Games](https://www.zmangames.com/en/games/love-letter/).

This project exposes the following top-level Python packages:

- **`loveletter`** – 
  The core package with all the game logic and nothing else.
- **`loveletter_multiplayer`** –
  A sample multiplayer engine based on a client/server model for playing games over a
  network using TCP sockets.
  It uses `asyncio` and `async`/`await` as its "concurrency framework", so to speak.
  Depends on `loveletter`.
- **`loveletter_cli`** –
  A command line user interface for single- or multiplayer games. It's intended just
  for debugging and testing purposes.

  ![CLI screenshot](docs/img/cli-screenshot.png)

The reason these are split into several top-level packages instead of having all be part
of a single `loveletter` package is to make it more modular and easier to replace any 
of the components:
for example, one could implement a different user interface for local-only games, and
they would only need the core `loveletter` package; 
or one could implement a different multiplayer engine;
etc.
