import asyncio
import struct
import tkinter as tk
from tkinter import scrolledtext, Button, Frame, Label
from PIL import Image, ImageTk
from datetime import datetime

# Command definitions (align with pydealerclient protocol)
CMD_LOGIN = 0xAB0002
CMD_LOGIN_R = 0xBA0002  # Response for login
CMD_START_PREDICT = 0xBA0003
CMD_PREDICT_RESULT = 0xAB0004  # Prediction result from dealer client
CMD_KEEPALIVE = 0xAB0001  # Keep-alive command
CMD_DISPATCH_INDEX = 0xBA0006  # Dispatch index command
CMD_STOP_PREDICT = 0xBA0004  # Command for stopping prediction

# Suit and value maps for interpreting results from pydealer
SUIT_MAP = {
    0: "Clubs",
    1: "Diamonds",
    2: "Spades",
    3: "Hearts"
}

VALUE_MAP = {
    1: "Ace", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6",
    7: "7", 8: "8", 9: "9", 10: "10", 11: "Jack",
    12: "Queen", 13: "King"
}

def get_suit(card_val):
    # Determine suit by integer division
    suit_index = card_val // 16 # cardinfo以16為單位
    return SUIT_MAP.get(suit_index, "Unknown")

def get_card_value(card_val):
    # Determine card rank by taking remainder
    rank = card_val % 16
    return VALUE_MAP.get(rank, "Unknown")

# File path for card images
IMAGE_FOLDER = "./card_shown_ui/greywyvern-cardset/"

def get_suit_letter(card_val):
    # Determine suit letter for filename based on integer division
    suit_index = card_val // 16
    return {0: "C", 1: "D", 2: "S", 3: "H"}.get(suit_index, "Unknown")

def get_card_filename(card_val):
    # Construct the filename based on suit letter and card rank
    rank = card_val % 16
    rank_str = f"{rank:02}"  # Two-digit format, e.g., Ace is "01"
    suit_letter = get_suit_letter(card_val)
    return f"{suit_letter}{rank_str}.png" if suit_letter != "Unknown" else None

class MockDealerAppProtocol(asyncio.Protocol):
    def __init__(self, app):
        self.app = app
        self.transport = None
        self.logged_in = False
        self.start_predict_count = 0
        self.game_timestamp = datetime.now().strftime("%m%d_%H%M%S")

    def connection_made(self, transport):
        self.transport = transport
        self.app.protocol = self  # Set the protocol reference in MockDealerApp
        self.app.log("Connection established with pydealerclient.")

    def data_received(self, data):
        # Parse command and handle based on protocol
        cmd, size, seq = struct.unpack("!3I", data[:12])
        body = data[12:]

        if cmd == CMD_LOGIN:
            self.handle_login()
        elif cmd == CMD_KEEPALIVE:
            self.handle_keep_alive()
        elif cmd == CMD_PREDICT_RESULT:
            self.handle_prediction_result(body)
        else:
            self.app.log(f"Unknown command received: {hex(cmd)}")

    def handle_login(self):
        # Handle login command and send acknowledgment
        self.logged_in = True
        self.app.log("Received login command. Sending acknowledgment.")

        code = 0  # Assuming 0 means success
        gmtype = b'BAC\x00'  # Example game type
        vid = b"B004"  # 4-byte vid

        # Format the body as 12 bytes: code (4 bytes), gmtype (4 bytes), vid (4 bytes)
        body = struct.pack("!I4s4s", code, gmtype, vid)

        # Send the CMD_LOGIN_R packet with the constructed body
        packet = struct.pack("!3I", CMD_LOGIN_R, 12 + len(body), 0) + body
        self.transport.write(packet)

    def handle_keep_alive(self):
        # Respond to keep-alive command
        # self.app.log("Received keep-alive command.")
        pass

    def send_start_predict(self):
        """
        Send the start prediction command with a unique game code using the current timestamp in 'YYYYMMDD_HHMMSS' format.
        """
        gmcode = f"{self.game_timestamp}_{self.start_predict_count}".encode().ljust(14, b'\x00')
        gmstate = 2
        body = struct.pack("!14sh", gmcode, gmstate)

        packet = struct.pack("!3I", CMD_START_PREDICT, 12 + len(body), 0) + body
        self.transport.write(packet)
        self.app.log(f"Sent start prediction command for game: {self.game_timestamp}_{self.start_predict_count}")
        self.start_predict_count += 1

    def send_stop_predict(self):
        """
        Send the stop prediction command with the last timestamp-based game code.
        """
        gmcode = f"{self.game_timestamp}_{self.start_predict_count}".encode().ljust(14, b'\x00')
        gmstate = 0  # gmstate 0 indicates stopping prediction

        body = struct.pack("!14sh", gmcode, gmstate)
        packet = struct.pack("!3I", CMD_STOP_PREDICT, 12 + len(body), 0) + body
        self.transport.write(packet)
        self.app.log("Sent stop prediction command.")

    def dispatch_index(self, index):
        # Construct dispatch index command packet with mcode and index
        mcode = b"BAC".ljust(14, b'\x00')
        body = struct.pack("!14sh", mcode, index)
        packet = struct.pack("!3I", CMD_DISPATCH_INDEX, 12 + len(body), 0) + body
        self.transport.write(packet)
        self.app.log(f"Sent dispatch index command for card index: {index}")

    def handle_prediction_result(self, body):
        if len(body) < 16:
            self.app.log(f"Received CMD_PREDICT_RESULT with insufficient body size: {len(body)} bytes")
            return

        gmcode, count = struct.unpack("!14sh", body[:16])
        gmcode = gmcode.decode('utf-8').rstrip('\x00')
        self.app.log(f"Game Code: {gmcode}, Result Count: {count}")

        entry_size = 12
        expected_body_size = 16 + count * entry_size
        if len(body) != expected_body_size:
            self.app.log(f"Expected body size {expected_body_size}, but got {len(body)}")
            return

        offset = 16
        for i in range(count):
            entry_data = body[offset:offset + entry_size]
            index, card_val, score = struct.unpack("!2hd", entry_data)
            offset += entry_size

            # Retrieve suit and card name
            suit = get_suit(card_val)
            card_name = get_card_value(card_val)

            result_text = (
                f"Prediction Result - Index: {index}, card_val from inference side: {card_val}, "
                f"Suits: {suit}, Card Value: ({card_name}), Score: {score:.4f}"
            )
            self.app.log(result_text)

            # Display card image for the corresponding index
            self.app.display_card_image(index, card_val)

    def connection_lost(self, exc):
        self.app.log("Connection lost with pydealerclient.")
        self.app.protocol = None
        self.logged_in = False

class MockDealerApp:
    def __init__(self, host='127.0.0.1', port=2331):
        self.host = host
        self.port = port
        self.protocol = None

        # 20241203 stacking cards scenario
        # Initialize card stacks for each index
        self.index_card_stacks = {i: [] for i in range(1, 7)}  # Dictionary for stacking cards per index

        # Set up a simple UI to display predictions
        self.root = tk.Tk()
        self.root.title("Mock Dealer App - Prediction Results")
        self.root.geometry("800x800")  # Increase window size to ensure all elements are visible

        # Text area for logs
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, width=80, height=15)
        self.text_area.pack(padx=10, pady=10)

        # 20241204 because of multicard detection on certain index, implement "new card game button"
        self.new_game_button = Button(self.root, text="Start New Card Game", command=self.start_new_game)
        self.new_game_button.pack(pady=10)

        # Start Prediction button
        self.start_button = Button(self.root, text="Start Prediction", command=self.start_prediction)
        self.start_button.pack(pady=5)

        # Frame for index dispatch buttons
        button_frame = Frame(self.root)
        button_frame.pack(pady=10)

        # Create buttons for each index (1 to 6)
        for i in range(1, 7):
            button = Button(button_frame, text=f"Dispatch Index {i}", command=lambda idx=i: self.dispatch_index(idx))
            button.grid(row=0, column=i-1, padx=5)

        # Stop Prediction button placed at the bottom of the dispatch indexes
        self.stop_button = Button(self.root, text="Stop Prediction", command=self.stop_prediction)
        self.stop_button.pack(pady=5)

        # Frame to hold card images in the specified order 5, 1, 3, 2, 4, 6
        self.image_frame = Frame(self.root)
        self.image_frame.pack(pady=10)

        # Custom order for displaying card indexes
        display_order = [5, 1, 3, 2, 4, 6]
        self.card_image_labels = {}
        for col, idx in enumerate(display_order):
            # Frame for each card display slot
            label_frame = Frame(self.image_frame, padx=5, pady=5, relief="solid", borderwidth=1)
            label_frame.grid(row=0, column=col)

            # Index label above the image
            index_label = Label(label_frame, text=f"Index {idx}")
            index_label.pack()

            # # Card image label without fixed width/height to allow image scaling
            # card_label = Label(label_frame, text="No Image")
            # card_label.pack()
            # self.card_image_labels[idx] = card_label  # Store each label for updating later

            # 20241204 add scroll bar for each index
            # Create a scrollable canvas
            canvas = tk.Canvas(label_frame, width=120, height=200, bg="white")
            canvas.pack(side=tk.LEFT)

            # Add a scrollbar
            scrollbar = tk.Scrollbar(label_frame, orient=tk.VERTICAL, command=canvas.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Configure canvas to work with scrollbar
            canvas.configure(yscrollcommand=scrollbar.set)
            # Bind the canvas to dynamically adjust the scrollable region
            def update_scrollregion(event, c=canvas):
                c.configure(scrollregion=c.bbox("all"))

            canvas.bind("<Configure>", update_scrollregion)

            # Store the canvas in the dictionary
            self.card_image_labels[idx] = canvas

    async def start_server(self):
        # Create the server with the protocol
        server = await asyncio.get_running_loop().create_server(lambda: MockDealerAppProtocol(self), self.host, self.port)
        self.log(f"Mock Dealer App is listening on {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

    def log(self, message):
        print(message)
        self.text_area.insert(tk.END, message + "\n")
        self.text_area.yview(tk.END)  # Scroll to the end of the text area

    def start_prediction(self):
        # Trigger start prediction command via the protocol instance
        if self.protocol:
            self.protocol.send_start_predict()
        else:
            self.log("No connection established. Unable to send start prediction command.")

    def stop_prediction(self):
        # Trigger stop prediction command via the protocol instance
        if self.protocol:
            self.protocol.send_stop_predict()
        else:
            self.log("No connection established. Unable to send stop prediction command.")

    def dispatch_index(self, index):
        # Trigger dispatch index command via the protocol instance
        if self.protocol:
            self.protocol.dispatch_index(index)
        else:
            self.log(f"No connection established. Unable to dispatch index {index}.")

    # # 20241203 stacking cards scenario
    # def display_card_image(self, index, card_val):
    #     """
    #     Display a card image for the given index, stacking the cards visually such that part
    #     of the previous cards remain visible, like real card stacking.
    #     """
    #     filename = get_card_filename(card_val)
    #     if filename:
    #         image_path = f"{IMAGE_FOLDER}{filename}"
    #         try:
    #             # Open and resize the card image
    #             image = Image.open(image_path).resize((100, 150), Image.LANCZOS)
    #             photo = ImageTk.PhotoImage(image)

    #             # Stack cards for the given index
    #             label = self.card_image_labels.get(index)

    #             # Create a canvas for stacking if it doesn't already exist
    #             if not hasattr(label, "canvas"):
    #                 label.canvas = tk.Canvas(label, width=120, height=200, bg="white")
    #                 label.canvas.pack()

    #                 # Initialize a list to hold image references for this index
    #                 label.canvas.image_refs = []

    #             # Compute the vertical offset for stacking cards
    #             stack_offset = 30 * len(label.canvas.image_refs)  # Adjust overlap as needed

    #             # Draw the new card on the canvas
    #             label.canvas.create_image(10, stack_offset, anchor="nw", image=photo)
    #             label.canvas.image_refs.append(photo)  # Keep a reference to prevent garbage collection

    #             self.log(f"Card stacked at index {index}: {card_val}")

    #         except FileNotFoundError:
    #             self.log(f"Image file {image_path} not found.")
    #         except Exception as e:
    #             self.log(f"Error displaying card at index {index}: {e}")

    # 20241204 index card scrolling scenario
    def display_card_image(self, index, card_val):
        """
        Display a card image for the given index, stacking the cards visually and
        enabling scrolling when there are too many cards to fit within the canvas.
        """
        filename = get_card_filename(card_val)
        if filename:
            image_path = f"{IMAGE_FOLDER}{filename}"
            try:
                # Open and resize the card image
                image = Image.open(image_path).resize((100, 150), Image.LANCZOS)
                photo = ImageTk.PhotoImage(image)

                # Stack cards for the given index
                canvas = self.card_image_labels[index]

                # Initialize a list to hold image references for this index
                if not hasattr(canvas, "image_refs"):
                    canvas.image_refs = []  # Initialize image references list

                # Compute the vertical offset for stacking cards
                stack_offset = 30 * len(canvas.image_refs)

                # Draw the new card on the canvas
                canvas.create_image(10, stack_offset, anchor="nw", image=photo)
                canvas.image_refs.append(photo)  # Keep a reference to prevent garbage collection

                # Update the scrollregion dynamically
                canvas.configure(scrollregion=canvas.bbox("all"))

                self.log(f"Card stacked at index {index}: {card_val}")

            except FileNotFoundError:
                self.log(f"Image file {image_path} not found.")
            except Exception as e:
                self.log(f"Error displaying card at index {index}: {e}")

    # def reset_card_images(self):
    #     # Clear all card images from the labels
    #     for idx, label in self.card_image_labels.items():
    #         label.config(image="", text="No Image")
    #         label.image = None  # Remove reference to image
    #         label.update_idletasks()

    # # 20241203 stacking cards scenario
    def reset_card_images(self):
        """
        Clear all card stacks and reset the images on the UI for all indices.
        """
        # Clear the card stacks
        self.index_card_stacks = {i: [] for i in range(1, 7)}

        # Reset the UI elements
        for idx, canvas in self.card_image_labels.items(): # self.card_image_labels[idx] = canvas
            if canvas:  # Check if the label has a canvas for stacking
                canvas.delete("all")  # Clear all drawings from the canvas
                canvas.image_refs = []  # Clear the image references

        self.log("All card images and stacks have been reset.")

    # 20241204 because of multicard detection on certain index, implement "new card game button"
    def start_new_game(self):
        """
        Start a new card game. Reset the game state and notify the server to begin a new game.
        """
        # Reset card images and stacks
        self.reset_card_images()

        # set game timestamp to indicate which game currently is
        self.game_timestamp = datetime.now().strftime("%m%d_%H%M%S")  # Format the current timestamp

        # Send a reset command or notify the server of the new game
        self.log(f"Starting a new card game : {self.game_timestamp}")
        self.start_predict_count = 0

    def run(self):
        # Create the event loop and set it for the current context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(self.start_server())

        # Run the Tkinter mainloop while updating the asyncio event loop periodically
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.poll_asyncio_loop(loop)
        self.root.mainloop()

    def poll_asyncio_loop(self, loop):
        # Poll the asyncio event loop and schedule the next poll
        loop.call_soon(self.root.after, 100, self.poll_asyncio_loop, loop)
        loop.run_until_complete(asyncio.sleep(0))

    def on_closing(self):
        self.root.quit()
        self.root.destroy()

def main():
    app = MockDealerApp('127.0.0.1', 2331)
    app.run()

if __name__ == "__main__":
    main()