#!/usr/bin/env python

from optparse import OptionParser
import subprocess
import sys, os
import logging
from StringIO import StringIO
from contextlib import contextmanager

def main():
	p = OptionParser(usage="%prog [OPTIONS] feed_or_alias path_env")
	p.add_option('--mode', type='choice', default='prepend', help='how the new path is to be inserted into the environment variable', choices=['prepend','append','replace'])
	p.add_option('--insert', '-i', default='', help='local path (inside implementation)')

	opts, args = p.parse_args()
	opts.url, opts.environment = args

	if not "://" in opts.url:
		url = check_output(['0alias', '-r', opts.url])
		opts.url = url.strip()

	# get selections doc:
	selections_string = check_output(['0launch', '--get-selections', opts.url])

	# resolve selections and download all (transitively) required implementations
	from zeroinstall.injector import qdom, run, selections
	sels = selections.Selections(qdom.parse(StringIO(selections_string)))
	download_missing_selections(sels)

	# copy the previous env
	old_env = os.environ.copy()

	with replaced_stdout():
		run.execute_selections(sels, args, dry_run=True)
	insert_root_implementation(opts, sels)

	# print out changes to env in a way that can be eval`d by the shell
	summarise_env_changes(old_env)

def check_output(cmd, *a, **kw):
	p = subprocess.Popen(cmd, *a, stdout=subprocess.PIPE, **kw)
	out, _ = p.communicate()
	if p.returncode != 0:
		print out
		raise RuntimeError("command failed with returncode %d: %r" % (p.returncode, cmd))
	return out

@contextmanager
def replaced_stdout():
	old_stdout = sys.stdout
	new_stdout = StringIO()
	sys.stdout = new_stdout
	try:
		yield
	finally:
		sys.stdout = old_stdout

def summarise_env_changes(old_env):
	new_env = os.environ.copy()
	from bash_escape import escape
	for k in set(old_env.keys() + new_env.keys()):
		old = old_env.get(k, None)
		new = new_env.get(k, None)
		if old != new:
			print "export %s=%s" % (k, escape(new))

def insert_root_implementation(opts, selections):
	root_impl = selections.selections[opts.url]
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
	main()
