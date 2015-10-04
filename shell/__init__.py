from __future__ import absolute_import, print_function
import collections
import argh
import contextlib
import logging
import os
import random
import s.cached
import s.colors
import s.hacks
import string
import subprocess
import sys
import types


_max_lines_stdout_cached = 1000


def run(*a, **kw):
    plain = kw.pop('plain', False)
    warn = kw.pop('warn', False)
    zero = kw.pop('zero', False)
    echo = kw.pop('echo', False)
    stdin = kw.pop('stdin', None)
    quiet = kw.pop('quiet', _state.get('quiet', False))
    callback = kw.pop('callback', None)
    stream = kw.pop('stream', _state.get('stream', False))
    popen = kw.pop('popen', False)
    log_or_print = _get_log_or_print(stream or echo)
    cmd = ' '.join(map(str, a))
    if stdin:
        with tempdir(cleanup=False):
            stdin_file = os.path.abspath('stdin')
            with open(stdin_file, 'w') as f:
                f.write(stdin)
        cmd = 'cat %(stdin_file)s | %(cmd)s' % locals()
    log_or_print('$(%s) [cwd=%s]' % (s.colors.yellow(cmd), os.getcwd()))
    if plain:
        (subprocess.check_call if stream else subprocess.check_output)(cmd, **_call_kw)
    else:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **_call_kw)
        if popen:
            return proc
        output = _process_lines(proc, log_or_print, callback)
        if warn:
            log_or_print('exit-code=%s from cmd: %s' % (proc.returncode, cmd))
            return {'output': output, 'exitcode': proc.returncode, 'cmd': cmd}
        elif zero:
            return proc.returncode == 0
        elif proc.returncode != 0:
            output = '' if stream else output
            if quiet:
                sys.exit(proc.returncode)
            else:
                raise Exception('%s\nexitcode=%s from cmd: %s, cwd: %s' % (output, proc.returncode, cmd, os.getcwd()))
        return output


def listdir(path='.', abspath=False):
    return list_filtered(path, abspath, lambda *a: True)


def dirs(path='.', abspath=False):
    return list_filtered(path, abspath, os.path.isdir)


def files(path='.', abspath=False):
    return list_filtered(path, abspath, os.path.isfile)


def list_filtered(path, abspath, predicate):
    path = os.path.expanduser(path)
    resolve = lambda x: os.path.abspath(os.path.join(path, x))
    return [resolve(x) if abspath else x
            for x in sorted(os.listdir(path))
            if predicate(os.path.join(path, x))]


@contextlib.contextmanager
def cd(path='.'):
    orig = os.path.abspath(os.getcwd())
    if path:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            run('mkdir -p', path)
        os.chdir(path)
    try:
        yield
    except:
        raise
    finally:
        os.chdir(orig)


@contextlib.contextmanager
def tempdir(cleanup=True, intemp=True):
    while True:
        try:
            letters = string.letters
        except AttributeError:
            letters = string.ascii_letters
        path = ''.join(random.choice(letters) for _ in range(20))
        path = os.path.join('/tmp', path) if intemp else path
        if not os.path.exists(path):
            break
    run('mkdir -p', path)
    try:
        with cd(path):
            yield path
    except:
        raise
    finally:
        if cleanup:
            run(sudo(), 'rm -rf', path)


def dispatch_commands(_globals, _name_):
    """
    dispatch all top level functions not starting with underscore
    >>> # dispatch_commands(globals(), __name__)
    """
    try:
        argh.dispatch_commands(sorted([
            v for k, v in _globals.items()
            if isinstance(v, types.FunctionType)
            and v.__module__ == _name_
            and not k.startswith('_')
            and k != 'main'
        ], key=lambda x: x.__name__))
    except KeyboardInterrupt:
        sys.exit(1)


def less(text):
    if text:
        with tempdir():
            with open('text', 'w') as f:
                f.write(text + '\n\n')
            run('less -cR text', plain=True, stream=True)


@s.cached.func
def sudo():
    """
    used in place of "sudo", returns "sudo" if you can sudo, otherwise ""
    """
    try:
        run('sudo whoami')
        return 'sudo'
    except:
        return ''


_state = {}


def _set_state(key):
    @contextlib.contextmanager
    def fn():
        orig = _state.get(key)
        _state[key] = True
        try:
            yield
        except:
            raise
        finally:
            del _state[key]
            if orig is not None:
                _state[key] = orig
    return fn


set_stream = _set_state('stream')


set_quiet = _set_state('quiet')


def _process_lines(proc, log, callback=None):
    lines = collections.deque(maxlen=_max_lines_stdout_cached)
    def process(line):
        line = s.hacks.stringify(line).rstrip()
        if line.strip():
            log(line)
            lines.append(line)
        if callback:
            callback(line)
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        process(line)
    proc.wait()
    return '\n'.join(lines)


def _get_log_or_print(should_log):
    def fn(x):
        if should_log:
            if hasattr(logging.root, '_ready'):
                logging.info(x)
            else:
                sys.stdout.write(x.rstrip() + '\n')
                sys.stdout.flush()
    return fn


_call_kw = {'shell': True, 'executable': '/bin/bash', 'stderr': subprocess.STDOUT}
