import argparse
import log
import adb
import ocr
import rifornimento


def main():
    ap = argparse.ArgumentParser(description='Test a step per invio risorse (rifornimento)')
    ap.add_argument('--porta', required=True)
    ap.add_argument('--nome', default='ISTANZA')
    ap.add_argument('--step', type=int, choices=[1,2,3,4], required=True)
    ap.add_argument('--max-swipe', type=int, default=None)
    args = ap.parse_args()

    # In manuale: serve connettere ADB
    adb.connetti(args.porta)

    if args.step == 1:
        ok = rifornimento.test_step1_home_to_membri(args.porta, args.nome, logger=log.logger)

    elif args.step == 2:
        ok = rifornimento.test_step2_find_avatar(args.porta, args.nome, logger=log.logger, max_swipe=args.max_swipe)

    elif args.step == 3:
        ok = rifornimento.test_step3_open_supply_mask(args.porta, args.nome, logger=log.logger)

    elif args.step == 4:
        # Flusso completo: legge risorse reali dal deposito, poi chiama esegui_rifornimento
        screen = adb.screenshot(args.porta)
        risorse = ocr.leggi_risorse(screen) if screen else {}
        log.logger(args.nome, f"[RIF][S4] Deposito letto: " + " | ".join(
            f"{r}={v/1e6:.1f}M" for r, v in risorse.items() if v >= 0
        ))
        n = rifornimento.esegui_rifornimento(
            porta        = args.porta,
            nome         = args.nome,
            pomodoro_m   = risorse.get("pomodoro", -1) / 1e6 if risorse.get("pomodoro", -1) >= 0 else -1,
            legno_m      = risorse.get("legno",    -1) / 1e6 if risorse.get("legno",    -1) >= 0 else -1,
            acciaio_m    = risorse.get("acciaio",  -1) / 1e6 if risorse.get("acciaio",  -1) >= 0 else -1,
            petrolio_m   = risorse.get("petrolio", -1) / 1e6 if risorse.get("petrolio", -1) >= 0 else -1,
            logger       = log.logger,
            ciclo        = 0,
        )
        log.logger(args.nome, f"[RIF][S4] Spedizioni totali: {n}")
        ok = n >= 0

    print('OK' if ok else 'FAIL')


if __name__ == '__main__':
    main()