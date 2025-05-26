import click
from cfn_sanitizer.scanner import load_template
from cfn_sanitizer.sanitizer import sanitize_template
from cfn_sanitizer.utils import save_template, save_report

@click.command()
@click.option('-i', '--input',  'input_path', required=True,
              help='Path to .yaml/.yml/.json CloudFormation template')  # click.option docs :contentReference[oaicite:11]{index=11}
@click.option('-o', '--output', 'output_path', required=True,
              help='Path to write sanitized template')
@click.option('-r', '--report',  'report_path', default=None,
              help='Optional JSON path to write replacement report')
def main(input_path, output_path, report_path):
    """Sanitize a CloudFormation template by replacing hardcoded secrets."""
    template, fmt = load_template(input_path)
    sanitized, report = sanitize_template(template)
    save_template(output_path, sanitized, fmt)
    if report_path:
        save_report(report_path, report)
    click.echo(f"Sanitized template: {output_path}")
    if report_path:
        click.echo(f"Report saved to: {report_path}")

if __name__ == '__main__':
    main()
