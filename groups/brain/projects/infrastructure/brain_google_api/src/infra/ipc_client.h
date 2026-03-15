#ifndef IPC_CLIENT_H
#define IPC_CLIENT_H

#include <stdbool.h>

typedef void (*IPCMessageHandler)(const char *msg_type, const char *payload);

int ipc_client_init(const char *service_name, const char *socket_path);
int ipc_client_register(void);
int ipc_client_send(const char *to, const char *message_type, const char *message);
int ipc_client_receive(char **out_type, char **out_payload);
int ipc_client_notify(const char *message);
void ipc_client_free(void);

#endif
