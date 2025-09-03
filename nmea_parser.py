from time import sleep
import signal
import serial
import pynmea2
import datetime
import decimal
import pandas as pd
import numpy as np
import chart_studio.plotly as py
# import plotly.plotly as py
import plotly.tools as tls
import plotly.graph_objs as go
import plotly.express as px
# import dash
from dash import Dash, html, dcc, dash_table   #, callback
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
# import random
from collections import deque
# import socket
# import nmea
# from nmea import input_stream
# import time


# HOST = "localhost"
# PORT = 23000
# DELIMITER = b"\r\n"
# BUFFER_SIZE = 4096
global_max_speed = 0
global_verbose = False
global_max_errors = 10
ser = serial.serial_for_url("socket://localhost:23000/logging=debug")  #, baudrate=36400)


# Create a Signal Handler for Signals.SIGINT:  CTRL + C
def SignalHandler_SIGINT(SignalNumber,Frame):
    print("Closing serial")
    ser.close()
    exit()


signal.signal(signal.SIGINT,SignalHandler_SIGINT)


def parse_as_dict(sentence, check=True, verbose=False):
    ret = {}

    if verbose:
        ret["sentence"] = sentence

    ret['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

    obj = pynmea2.parse(sentence, check=check)
    ret["data_type"] = obj.__class__.__name__

    for f in obj.fields:
        desc = f[0]
        attr = f[1]
        val = getattr(obj, attr)

        if not val and not verbose:
            continue

        # Workaround because msgpack will not serialize datetime.date, datetime.time and decimal.Decimal
        if isinstance(val, datetime.date):
            val = str(val)
        elif isinstance(val, datetime.time):
            val = str(val)
        elif isinstance(val, decimal.Decimal):
            val = float(val)
        # TODO: Temp fix to get correct types because pynmea2 does not handle it
        elif attr.startswith("num_") or attr.endswith("_num") or "_num_" in attr:
            val = int(val)
        elif attr.startswith("snr_") or attr.startswith("azimuth_"):
            val = float(val)

        ret[attr] = val if not verbose else {
            "description": desc,
            "value": val
        }

    return ret


# ################## Static plot experiment like with file data
# wind_list = []  #[["timestamp", "data_type", "wind_angle", "reference", "wind_speed", "wind_speed_units"]]
# data = str(ser.readline().decode('utf-8').rstrip())
# cnt = 0
#
# while data and cnt < 10:
#     # print(data)
#     val = parse_as_dict(data, verbose=True)
#     if val["data_type"] == "MWV":
#         if global_verbose:
#             print("got", cnt, val)
#         wind_list.append([val["timestamp"], val["data_type"], val["wind_angle"]["value"], val["reference"]["value"], val["wind_speed"]["value"], val["wind_speed_units"]["value"]])
#         cnt += 1
#     data = str(ser.readline().decode('utf-8').rstrip())
#     # ser.flushOutput()
# ser.close()
#
# print("List")
# print(wind_list)
#
# wind_df = pd.DataFrame(wind_list, columns=["timestamp", "data_type", "wind_angle", "reference", "wind_speed", "wind_speed_units"])
# print(wind_df)
#
# fig = px.bar(wind_df, x="timestamp", y="wind_speed")
#
# fig.show()
#
# # fig = go.Figure(go.Indicator(
# #     mode = "gauge+number",
# #     value = 0,
# #     domain = {'x': [0, 1], 'y': [0, 1]},
# #     title = {'text': "Speed"}))
# ######################### End Static plot experiment


def get_speed(do_ts = False):
    errors = 0
    # ser = serial.serial_for_url("socket://localhost:23000/logging=debug")
    data = str(ser.readline().decode('utf-8').rstrip())
    while data:
        try:
            # print("Data is:", data)
            val = parse_as_dict(data, verbose=True)
            # print("Val is:", val)
            if val['data_type'] == "MWV":
                # ser.close()
                if errors > 0:
                    print("Fixed errors", errors)
                errors = 0
                if global_verbose:
                    print("Good data:", data)
                if do_ts:
                    return val["wind_speed"]["value"], val["timestamp"]
                else:
                    return val["wind_speed"]["value"]
        except:
            errors += 1
            if global_verbose or errors > global_max_errors:
                print("Errors:", errors, "and bad data:", data)
        # sleep(0.5)
        data = str(ser.readline().decode('utf-8').rstrip())
    return -1

# ###### Start test dynamic line plot
# X = deque(maxlen=200)
# # X.append(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'))
# X.append(1)
#
# Y = deque(maxlen=200)
# Y.append(1)
#
# app = Dash(__name__)
#
# app.layout = html.Div(
#     [
#         dcc.Graph(id='live-graph', animate=True),
#         dcc.Interval(
#             id='graph-update',
#             interval=1000,
#             n_intervals=0
#         ),
#     ]
# )
#
#
# @app.callback(
#     Output('live-graph', 'figure'),
#     [Input('graph-update', 'n_intervals')]
# )
#
#
# def update_graph_scatter(n):
#     speed, timestamp = get_speed()
#     # X.append(timestamp)
#     X.append(X[-1] + 1)
#     Y.append(speed)
#     # Y.append(Y[-1] + Y[-1] * random.uniform(-0.1, 0.1))
#
#     data = go.Scatter(
#         x=list(X),
#         y=list(Y),
#         name='Scatter',
#         mode='lines+markers'
#     )
#
#     return {'data': [data],
#             'layout': go.Layout(xaxis=dict(range=[min(X), max(X)]), yaxis=dict(range=[min(Y), max(Y)]), )}
# ####End Test dynamic line plot


# #### Start test indicator
# app = Dash(__name__)
#
# app.layout = html.Div(
#     [
#         dcc.Graph(id='live-graph', animate=True),
#         dcc.Interval(
#             id='graph-update',
#             n_intervals=0
#         ),
#     ]
# )
#
#
# @app.callback(
#     Output('live-graph', 'figure'),
#     [Input('graph-update', 'n_intervals')]
# )
#
#
# def update_graph_indicator(n):
#     global global_max_speed
#     speed = get_speed(do_ts=False)
#     if speed > global_max_speed:
#         global_max_speed = speed
#
#     data = go.Indicator(
#         value=speed,
#         name='Indicator',
#         mode="gauge+number+delta",
#         title={'text': "Wind Speed"},
#         domain={'x': [0, 0.5], 'y': [0, 0.5]},
#         delta = {'reference': global_max_speed},
#         gauge={'axis': {'range': [None, 30]},
#                'steps': [
#                    {'range': [0, 10], 'color': "lightgray"},
#                    {'range': [10, 20], 'color': "gray"}],
#                'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': global_max_speed}}
#     )
#
#     return {'data': [data]}
# ######## End Test Indicator

# ############### Test radial plots
# df = px.data.wind()
#
# def update_graph_indicator(n):
#     fig = px.line_polar(df, r="frequency", theta="direction", color="strength", line_close=True,
#                     color_discrete_sequence=px.colors.sequential.Plasma_r,
#                     template="plotly_dark",)
#
#
# ############### End test radial plots

#  TEST Table

# app.layout = dash_table.DataTable(df.to_dict('records'), [{"name": i, "id": i} for i in df.columns])

app = Dash(__name__)
# app = Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])

# speed = get_speed(do_ts=False)
speed_dict_init = {"Speed": 0, "Max": global_max_speed}
print(speed_dict_init)
print([{"name": i, "id": i} for i in speed_dict_init.keys()])

# app.layout = dash_table.DataTable([speed_dict], [{"name": i, "id": i} for i in speed_dict.keys()])

app.layout = html.Div([
    html.H1('Mahdee Apparent Windspeeds'),
    dcc.Interval(id='table-update',interval=1000,n_intervals=0),
    dash_table.DataTable(id='table',
        data=[speed_dict_init],
        columns=[{"name": i, "id": i} for i in speed_dict_init.keys()])
     # rows=[{}],
     # row_selectable=False,
     # filterable=True,
     # sortable=False,
     # editable=False)
])

@app.callback(
    Output('table', 'rows'),
    [Input('table-update', 'n_intervals')]
)

# app.layout = dbc.Container([
#     dbc.Label('Click a cell in the table:'),
#     dash_table.DataTable(speed_dict, id='tbl'),  #,[{"name": i, "id": i} for i in speed_dict.keys()], id='tbl'),
#     # dash_table.DataTable(df.to_dict('records'),[{"name": i, "id": i} for i in df.columns], id='tbl'),
#     dbc.Alert(id='tbl_out'),
# ])

# @app.callback(Output('tbl_out', 'children'), Input('tbl', 'active_cell'))
#
#
# def update_graphs(active_cell):
#     return str(active_cell) if active_cell else "Click the table"


def update_table(n):
    global global_max_speed
    speed = get_speed(do_ts=False)
    if speed > global_max_speed:
        global_max_speed = speed
    speed_dict = {"Speed": speed, "Max": global_max_speed}
    print("Update:", speed_dict)

    # # data = go.Table([speed_dict], [{"name": i, "id": i} for i in speed_dict.keys()])
    data = dash_table.DataTable(
        # value=speed_dict,
        id='table',
        data = [speed_dict],
        columns = [{"name": i, "id": i} for i in speed_dict.keys()]
        # name='Table',
        # title={'text': "Wind Speed"},
        # domain={'x': [0, 0.5], 'y': [0, 0.5]},
        # delta = {'reference': global_max_speed},
        # gauge={'axis': {'range': [None, 30]},
        #        'steps': [
        #            {'range': [0, 10], 'color': "lightgray"},
        #            {'range': [10, 20], 'color': "gray"}],
        #        'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': global_max_speed}}
    )

    return [speed_dict]



if __name__ == '__main__':
    # app.run(debug=True)
    app.run_server()
    # app.run_server(debug=True, use_reloader=False)  # Turn off reloader if inside Jupyter




####################
# app_dash = dash.Dash(__name__, server=app, url_base_pathname='/dash/')
#
# app_dash.layout = html.Div([
#     dcc.Graph(id='live-update-graph'),
#     dcc.Interval(
#         id='interval-component',
#         interval=1*1000,  # in milliseconds
#         n_intervals=0
#     )
# ])
#
# @app_dash.callback(Output('live-update-graph', 'figure'),
#                    Input('interval-component', 'n_intervals'))
# def update_graph(n):
#     # Here you would fetch the latest data
#     # For this example, we will just return a random value
#     data = random.randint(1, 100)
#     figure = {
#         'data': [
#             {'x': [n], 'y': [data], 'type': 'line', 'name': 'Random Data'},
#         ],
#         'layout': {
#             'title': 'Real-Time Data Streaming'
#         }
#     }
#     return figure


















# class Buffer(object):
#     def __init__(self, sock):
#         self.sock = sock
#         self.buffer = b""
#
#     def get_line(self):
#         while b"\r\n" not in self.buffer:
#             data = self.sock.recv(BUFFER_SIZE)
#             if not data: # socket is closed
#                 return None
#             self.buffer += data
#         line, sep, self.buffer = self.buffer.partition(b"\r\n")
#         return line.decode()
#
# sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# # sock.bind((HOST, PORT))
# sock.connect((HOST, PORT))
# # sock.listen()
# print(f"Server listening on {HOST}:{PORT}")
#
# conn, addr = sock.accept()
# print("Connected by", addr)
#
# buff = Buffer(conn)
# while True:
#     line = buff.get_line()
#     if line is None:
#         break
#     print("Received message: ", line)
#
# conn.close()
# sock.closed()


# client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# client_socket.connect(('localhost', 23000))
#
#
#
#
# while True:
#     time.sleep(5)
#     data = client_socket.recv(512, )
#     if data.lower() == 'q':
#         client_socket.close()
#         break
#
#     print("RECEIVED: %s" % data)
#     data = input("SEND( TYPE q or Q to Quit):")
#     client_socket.send(data)
#     if data.lower() == 'q':
#         client_socket.close()
#         break
#
#
# stream = serial. #nmea.input_stream. # input_stream.GenericInputStream(client_socket)  # InputFileStream(client_socket)
#
# print(stream)
#
# with stream:
#     print(stream.get_line())
#
