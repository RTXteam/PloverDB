#!/usr/bin/env python3
import argparse
import logging
import subprocess


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        handlers=[logging.StreamHandler()])

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("access_key", nargs="?", default=None)
    arg_parser.add_argument("secret_key", nargs="?", default=None)
    args = arg_parser.parse_args()

    if args.access_key and args.secret_key:
        logging.info("Setting up awscli using provided keypair")
        subprocess.check_call(["apt-get", "update"])
        subprocess.check_call(["apt-get", "install", "-y", "awscli"])
        subprocess.check_call(["aws", "configure", "set", "default.region", "us-west-2"])
        subprocess.check_call(["aws", "configure", "set", "aws_access_key_id", args.access_key])
        subprocess.check_call(["aws", "configure", "set", "aws_secret_access_key", args.secret_key])
    else:
        logging.info("Not setting up awscli because keypair wasn't provided")


if __name__ == "__main__":
    main()
