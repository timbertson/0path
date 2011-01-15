#!/usr/bin/env python

from optparse import OptionParser
import subprocess
import sys, os
import logging
from StringIO import StringIO
from bash_escape import escape
from zeroinstall.injector import qdom, run, selections

def main():
	p = OptionParser(usage="""0path [OPTIONS] feed_or_alias [envvar]""", add_help_option=False)
	p.add_option('--mode', type='choice', default='prepend', help='how the new path is to be inserted into the environment variable', choices=['prepend','append','replace'])
	p.add_option('--insert', '-i', default='', help='local path (inside implementation)')
	p.add_option('--help', '-h', action='store_true', default=False, help="you're reading it")

	opts, args = p.parse_args()

	if opts.help:
		raise AssertionError(p.get_usage())
	assert len(args) in (1,2), p.get_usage()
	opts.url = args.pop(0)
	opts.environment = args[0] if args else None

	if not ("://" in opts.url or opts.url.endswith(".xml")):
		try:
			url = check_output(['0alias', '-r', opts.url])
			opts.url = url.strip()
		except CommandError, e:
			puts("warn: %s" % (e,))

	# get selections doc:
	selections_string = check_output(['0launch', '-c', '--get-selections', opts.url])

	# resolve selections and download all (transitively) required implementations
	sels = selections.Selections(qdom.parse(StringIO(selections_string)))
	download_missing_selections(sels)
	sels = sels.selections

	# copy the previous env
	old_env = os.environ.copy()
	apply_environment_bindings(sels)
	if opts.environment:
		insert_root_implementation(opts, sels)

	# print out changes to env in a way that can be eval'd by the shell
	summarise_env_changes(old_env)

def apply_environment_bindings(sels):
	for selection in sels.values():
		_do_bindings(selection, selection.bindings)
		for dep in selection.dependencies:
			dep_impl = sels[dep.interface]
			if not dep_impl.id.startswith('package:'):
				_do_bindings(dep_impl, dep.bindings)

from zeroinstall.injector.model import EnvironmentBinding
def _do_bindings(impl, bindings):
	for b in bindings:
		if isinstance(b, EnvironmentBinding):
			run.do_env_binding(b, _get_implementation_path(impl))

class CommandError(RuntimeError): pass
def check_output(cmd, *a, **kw):
	p = subprocess.Popen(cmd, *a, stdout=subprocess.PIPE, **kw)
	out, _ = p.communicate()
	if p.returncode != 0:
		print out
		raise CommandError("command failed with returncode %d: %r" % (p.returncode, cmd))
	return out

def summarise_env_changes(old_env):
	new_env = os.environ.copy()
	for k in set(old_env.keys() + new_env.keys()):
		old = old_env.get(k, None)
		new = new_env.get(k, None)
		if old != new:
			print "export %s=%s" % (k, escape(new))

def puts(s):
	print >> sys.stderr, s

def insert_root_implementation(opts, selections):
	root_impl = selections[opts.url]
	path = _get_implementation_path(root_impl)
	if opts.insert:
		path = os.path.join((path, opts.insert))
	existing_env = os.environ.get(opts.environment, None)
	mode = opts.mode
	if existing_env is None:
		mode = 'replace'

	if mode == 'prepend':
		os.environ[opts.environment] = os.pathsep.join((existing_env, path))
	elif mode == 'append':
		os.environ[opts.environment] = os.pathsep.join((path, existing_env))
	else:
		os.environ[opts.environment] = path


from zeroinstall.injector.iface_cache import iface_cache
def download_missing_selections(sels):
	from zeroinstall.injector import fetch
	from zeroinstall.injector.handler import Handler

	handler = Handler(dry_run = True)
	fetcher = fetch.Fetcher(handler)
	blocker = sels.download_missing(iface_cache, fetcher)
	if blocker:
		logging.info("Waiting for selected implementations to be downloaded...")
		handler.wait_for_blocker(blocker)

def _get_implementation_path(impl):
	return impl.local_path or iface_cache.stores.lookup_any(impl.digests)

if __name__ == '__main__':
	try:
		main()
	except AssertionError, e:
		puts(e)
		sys.exit(1)
	except Exception, e:
		import traceback
		puts(traceback.format_exc())
		sys.exit(1)
