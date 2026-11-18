"""MCP server exposing SSH/SFTP/SCP tools backed by paramiko."""

import os
from contextlib import contextmanager
from typing import Optional

import paramiko
from scp import SCPClient
from fastmcp import FastMCP

mcp = FastMCP("ssh-agent-mcp")


@contextmanager
def _connect(
    host: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
):
    client = paramiko.SSHClient()
    if strict_host_key_check:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
    }
    if key_path:
        kwargs["key_filename"] = key_path
        if key_passphrase:
            kwargs["passphrase"] = key_passphrase
        kwargs["look_for_keys"] = False
        kwargs["allow_agent"] = False
    else:
        if password is not None:
            kwargs["password"] = password
        kwargs["look_for_keys"] = password is None
        kwargs["allow_agent"] = password is None

    try:
        client.connect(**kwargs)
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass


def _sftp_mkdir_p(sftp, remote_dir: str) -> None:
    if not remote_dir or remote_dir in ("/", "."):
        return
    absolute = remote_dir.startswith("/") or remote_dir.startswith("\\")
    parts = [p for p in remote_dir.replace("\\", "/").split("/") if p not in ("", ".")]
    current = "/" if absolute else ""
    for part in parts:
        if absolute:
            current = (current.rstrip("/") + "/" + part) if current not in ("", "/") else "/" + part
        else:
            current = (current + "/" + part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            try:
                sftp.mkdir(current)
            except OSError:
                pass


@mcp.tool
def ssh_test_connection(
    host: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
) -> str:
    """Test SSH connectivity and authentication to a remote host."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            transport = ssh.get_transport()
            return f"OK: connected to {host}:{port} as {username} (transport active: {transport.is_active() if transport else False})"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def ssh_exec(
    host: str,
    command: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 60,
    strict_host_key_check: bool = False,
) -> str:
    """Execute a shell command on a remote host via SSH and return stdout/stderr/exit code."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            # send nothing to stdin
            stdin.close()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            return f"exit_code: {exit_code}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def scp_upload(
    host: str,
    local_path: str,
    remote_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 60,
    strict_host_key_check: bool = False,
    recursive: bool = False,
) -> str:
    """Upload a local file or directory to a remote host via SCP."""
    try:
        if not os.path.exists(local_path):
            return f"Error: local path not found: {local_path}"
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(local_path, remote_path, recursive=recursive)
            return f"OK: uploaded {local_path} -> {host}:{remote_path}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def scp_download(
    host: str,
    remote_path: str,
    local_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 60,
    strict_host_key_check: bool = False,
    recursive: bool = False,
) -> str:
    """Download a remote file or directory to a local path via SCP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with SCPClient(ssh.get_transport()) as scp:
                scp.get(remote_path, local_path, recursive=recursive)
            return f"OK: downloaded {host}:{remote_path} -> {local_path}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_upload(
    host: str,
    local_path: str,
    remote_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 60,
    strict_host_key_check: bool = False,
    mkdir_parents: bool = True,
) -> str:
    """Upload a local file to a remote path via SFTP."""
    try:
        if not os.path.isfile(local_path):
            return f"Error: local file not found: {local_path}"
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                if mkdir_parents:
                    _sftp_mkdir_p(sftp, os.path.dirname(remote_path.replace("\\", "/")))
                sftp.put(local_path, remote_path)
                st = sftp.stat(remote_path)
            return f"OK: uploaded {local_path} -> {host}:{remote_path} (size={st.st_size})"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_download(
    host: str,
    remote_path: str,
    local_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 60,
    strict_host_key_check: bool = False,
    mkdir_parents: bool = True,
) -> str:
    """Download a remote file to a local path via SFTP."""
    try:
        if mkdir_parents:
            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                sftp.get(remote_path, local_path)
                st = os.stat(local_path)
            return f"OK: downloaded {host}:{remote_path} -> {local_path} (size={st.st_size})"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_list(
    host: str,
    remote_path: str = ".",
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
) -> str:
    """List entries in a remote directory via SFTP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                entries = sftp.listdir_attr(remote_path)
            lines = []
            for e in entries:
                kind = "dir" if (e.st_mode and (e.st_mode & 0o040000)) else "file"
                lines.append(f"{e.filename}\t{kind}\t{e.st_size}")
            return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_mkdir(
    host: str,
    remote_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
    parents: bool = True,
) -> str:
    """Create a remote directory via SFTP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                if parents:
                    _sftp_mkdir_p(sftp, remote_path)
                else:
                    sftp.mkdir(remote_path)
            return f"OK: mkdir {host}:{remote_path}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_remove(
    host: str,
    remote_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
    recursive: bool = False,
) -> str:
    """Remove a remote file or directory via SFTP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                try:
                    st = sftp.stat(remote_path)
                    import stat as stmod
                    if stmod.S_ISDIR(st.st_mode):
                        if recursive:
                            # best-effort recursive delete
                            def _rmtree(p):
                                for e in sftp.listdir_attr(p):
                                    fp = p.rstrip("/") + "/" + e.filename
                                    if stmod.S_ISDIR(e.st_mode):
                                        _rmtree(fp)
                                    else:
                                        sftp.remove(fp)
                                sftp.rmdir(p)
                            _rmtree(remote_path)
                        else:
                            sftp.rmdir(remote_path)
                    else:
                        sftp.remove(remote_path)
                except FileNotFoundError:
                    return f"Error: not found: {remote_path}"
            return f"OK: removed {host}:{remote_path}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_rename(
    host: str,
    old_path: str,
    new_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
) -> str:
    """Rename/move a remote path via SFTP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                sftp.rename(old_path, new_path)
            return f"OK: renamed {host}:{old_path} -> {new_path}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def sftp_stat(
    host: str,
    remote_path: str,
    port: int = 22,
    username: Optional[str] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    timeout: int = 30,
    strict_host_key_check: bool = False,
) -> str:
    """Stat a remote path via SFTP."""
    try:
        with _connect(host, port, username, password, key_path, key_passphrase, timeout, strict_host_key_check) as ssh:
            with ssh.open_sftp() as sftp:
                st = sftp.stat(remote_path)
            import stat as stmod
            kind = "dir" if stmod.S_ISDIR(st.st_mode) else "file"
            return f"{remote_path}: {kind}, size={st.st_size}, mode={oct(st.st_mode)}, mtime={st.st_mtime}"
    except Exception as e:
        return f"Error: {e}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
