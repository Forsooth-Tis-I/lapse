import argparse

from lapse.signals.synthetic import create_synthetic_tenants, drop_synthetic_tenants


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or remove clearly labelled synthetic tenant graphs.")
    parser.add_argument("n", type=int, nargs="?")
    parser.add_argument("--drop", action="store_true")
    args = parser.parse_args()
    if args.drop:
        print(f"Dropped {drop_synthetic_tenants()} synthetic tenants.")
    elif args.n is None or args.n < 0:
        parser.error("provide a nonnegative tenant count, or --drop")
    else:
        print(f"Created {len(create_synthetic_tenants(args.n))} synthetic tenants.")


if __name__ == "__main__":
    main()
