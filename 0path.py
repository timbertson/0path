#!/usr/bin/env python

from optparse import OptionParser
import subprocess
import sys, os
import logging
from StringIO import StringIO
from bash_escape import escape
from zeroinstall.injector import qdom, run, selections

VERBOSE = True
def verbose(s):
	if VERBOSE:
		puts(s)

SELF_URL = 'http://gfxmonk.net/dist/0install/0path.xml'

def main():
	global VERBOSE
	p = OptionParser(usage="""0path [OPTIONS] feed_or_alias [envvar]""", add_help_option=False)
	p.add_option('--mode', type='choice', default='prepend', help='how the new path is to be inserted into the environment variable', choices=['prepend','append','replace'])
	p.add_option('--insert', '-i', default='', help='local path (inside implementation)')
	p.add_option('--undo', '-u', action='store_true', help='undo any changes already made by 0path')
	p.add_option('--command', '-c', default=None, help='add command-specific bindings')
	p.add_option('--quiet', '-q', action='store_false', dest='verbose', default=True, help='add command-specific bindings')
	p.add_option('--help', '-h', action='store_true', default=False, help="you're reading it")

	opts, args = p.parse_args()

	if opts.help:
		raise AssertionError(p.get_usage())

	# copy the previous env
	old_env = os.environ.copy()

	if opts.undo:
		self_sels = get_sels(SELF_URL)
		revert_env(os.environ, self_sels)
		with_env_changes(old_env, summarise_var)
		return

	assert len(args) in (1,2), p.get_usage()
	opts.url = args.pop(0)
	opts.environment = args[0] if args else None
	VERBOSE = opts.verbose

	if not ("://" in opts.url or opts.url.endswith(".xml")):
		try:
			url = check_output(['0alias', '-r', opts.url])
			opts.url = url.strip()
		except CommandError, e:
			puts("warn: %s" % (e,))

	command = opts.command or ''

	sels = get_sels(opts.url, command)
	self_sels = get_sels(SELF_URL)

	revert_env(os.environ, self_sels)
	apply_environment_bindings(sels)
	if opts.environment:
		insert_root_implementation(opts, sels)
	
	# backup all original values, for use next time we run 0find
	with_env_changes(old_env, backup_original_values)

	# print out changes to env in a way that can be eval'd by the shell
	with_env_changes(old_env, summarise_var)

def get_sels(url, command=''):
	# get selections doc:
	selections_string = check_output(['0install', 'select', '--console', '--xml', '--command=' + command, url])

	# resolve selections and download all (transitively) required implementations
	sels = selections.Selections(qdom.parse(StringIO(selections_string)))
	download_missing_selections(sels)
	sels = sels.selections
	return sels

ORIG_PREFIX = '_0find_'
def original_name(name):
	return ORIG_PREFIX + name

def original_env(env, name):
	return original_env.get(original_name(name), original_env.get(original_name, None))

def revert_env(env, self_sels):
	for k, v in list(env.items()):
		if k.startswith(ORIG_PREFIX):
			envname = k[len(ORIG_PREFIX):]
			env[envname] = v
			del env[k]

	def remove_item_from_env(key, path):
		values = env.get(key, None)
		if values:
			values = values.split(os.pathsep)
			try:
				values.remove(path)
			except ValueError:
				try:
					values.remove(os.path.join(path, ''))
				except ValueError:
					verbose("warning: path %s not found in envvar %s" % (path, key))
			env[key] = os.pathsep.join(filter(None, values))

	def _remove_bindings(impl, bindings):
		for b in bindings:
			if isinstance(b, EnvironmentBinding):
				remove_item_from_env(b.name, _get_implementation_path(impl))

	for selection in self_sels.values():
		_remove_bindings(selection, selection.bindings)
		for dep in selection.dependencies:
			dep_impl = self_sels[dep.interface]
			if not dep_impl.id.startswith('package:'):
				_remove_bindings(dep_impl, dep.bindings)


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

def with_env_changes(old_env, action):
	new_env = os.environ.copy()
	for k in set(old_env.keys() + new_env.keys()):
		old = old_env.get(k, None)
		new = new_env.get(k, None)
		if old != new:
			action(key=k, old=old, new=new)

def backup_original_values(key, old, new):
	if key.startswith(ORIG_PREFIX):
		return
	backup_key = (ORIG_PREFIX + key)
	if backup_key not in os.environ:
		os.environ[backup_key] = old or ''

def summarise_var(key, old, new):
	if not key.startswith(ORIG_PREFIX):
		verbose("Modifying: %s" % (key,))
	if new is None:
		print "unset %s" % (key,)
	else:
		print "export %s=%s" % (key, escape(new))
	
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
