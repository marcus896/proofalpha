# Reference Review: ccxt/ccxt

License: MIT License, from `LICENSE.txt`.

Files inspected:

- `LICENSE.txt`
- `README.md`
- top-level exchange abstraction layout

Patterns to replicate:

- Symbol metadata normalization ideas.
- Exchange capability discovery patterns.
- Error normalization concepts.

Patterns to avoid:

- Using CCXT as final Binance USD-M order semantics.
- Generic exchange abstractions that hide venue-specific constraints.
- Live exchange calls in default tests.

Security/dependency concerns:

- Generic connector APIs can mask Binance USD-M details.
- Official Binance docs must override connector conventions.

Native implementation decision:

- Use as a symbol/API-shape reference only.
- Implement `BinanceUSDMPVenueTranslator` natively from official Binance docs.
- Do not import as a production dependency.
