"""Store the Gemini key in SSM SecureString without putting it in a file."""
import getpass

from stack.aws import clients
from stack.config import settings


def main():
    cfg = settings('.env')
    key = getpass.getpass('Gemini API key (hidden): ').strip()
    if not key:
        raise ValueError('Gemini API key cannot be empty')

    aws = clients(cfg['AWS_REGION'])
    aws['ssm'].put_parameter(
        Name=cfg['GEMINI_KEY_PARAM'],
        Value=key,
        Type='SecureString',
        Overwrite=True
    )
    del key
    print('Gemini key stored in SSM SecureString. Value not displayed.')


if __name__ == '__main__':
    main()
